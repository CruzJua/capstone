const { test, describe, beforeEach, afterEach } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("fs");
const path = require("path");
const { createApp } = require("../src/server");
const {
    connectToDatabase,
    setDatabaseAdapter,
    resetDatabaseAdapter,
} = require("../src/db/mongo");
const {
    resolveRuntimeConfig,
    validateAppMode,
} = require("../src/config/mode");
const {
    setIngestionRunner,
    resetIngestionRunner,
    resolveSafePresetSourcePath,
} = require("../src/routes/documents");
const { resetLoginRateLimiter } = require("../src/routes/auth");
const { PRESET_TENANT_IDS } = require("../src/config/presets");

/**
 * In-memory MongoDB mock supporting multi-database isolation, operation auditing,
 * query matching ($in, $nin, $exists, $or, $regex), projections, and updates ($set, $setOnInsert, $push, $unset).
 */
class InMemoryDatabaseCluster {
    constructor() {
        this.databases = new Map();
        this.operationLog = [];
        this.failNextInsertOnCollection = null;
    }

    clearOperationLog() {
        this.operationLog.length = 0;
    }

    getProtectedResourceOps() {
        return this.operationLog.filter((entry) =>
            ["businesses", "doc_vectors", "ticket_logs"].includes(
                entry.collection
            )
        );
    }

    getDbForName(dbName) {
        if (!this.databases.has(dbName)) {
            this.databases.set(
                dbName,
                new InMemoryDatabase(dbName, this)
            );
        }
        return this.databases.get(dbName);
    }
}

function getNestedValue(obj, pathStr) {
    const parts = pathStr.split(".");
    let cur = obj;
    for (const part of parts) {
        if (cur === null || cur === undefined) return undefined;
        cur = cur[part];
    }
    return cur;
}

function setNestedValue(obj, pathStr, val) {
    const parts = pathStr.split(".");
    let cur = obj;
    for (let i = 0; i < parts.length - 1; i++) {
        const p = parts[i];
        if (typeof cur[p] !== "object" || cur[p] === null) {
            cur[p] = {};
        }
        cur = cur[p];
    }
    cur[parts[parts.length - 1]] = val;
}

function matchesCondition(value, cond) {
    if (cond && typeof cond === "object" && !Array.isArray(cond)) {
        if ("$exists" in cond) {
            const exists = value !== undefined;
            if (Boolean(cond.$exists) !== exists) return false;
        }
        if ("$in" in cond) {
            if (!Array.isArray(cond.$in) || !cond.$in.includes(value)) {
                return false;
            }
        }
        if ("$nin" in cond) {
            if (Array.isArray(cond.$nin) && cond.$nin.includes(value)) {
                return false;
            }
        }
        if ("$regex" in cond) {
            const re = new RegExp(cond.$regex, cond.$options || "");
            if (Array.isArray(value)) {
                if (!value.some((item) => re.test(String(item ?? "")))) {
                    return false;
                }
            } else if (!re.test(String(value ?? ""))) {
                return false;
            }
        }
        return true;
    }
    return value === cond;
}

function matchesQuery(doc, query = {}) {
    for (const [key, cond] of Object.entries(query)) {
        if (key === "$or" && Array.isArray(cond)) {
            const anyMatch = cond.some((sub) => matchesQuery(doc, sub));
            if (!anyMatch) return false;
            continue;
        }
        if (key === "messages.content" && Array.isArray(doc.messages)) {
            const contents = doc.messages.map((m) => m.content || "");
            if (!matchesCondition(contents, cond)) return false;
            continue;
        }
        const val = getNestedValue(doc, key);
        if (!matchesCondition(val, cond)) return false;
    }
    return true;
}

function applyProjection(doc, projection) {
    if (!doc) return null;
    const copy = JSON.parse(JSON.stringify(doc));
    if (!projection) return copy;
    for (const [field, flag] of Object.entries(projection)) {
        if (flag === 0) {
            delete copy[field];
        }
    }
    return copy;
}

class InMemoryCollection {
    constructor(name, dbName, cluster) {
        this.name = name;
        this.dbName = dbName;
        this.cluster = cluster;
        this.docs = [];
        this.indexes = [];
    }

    _record(op, filter = null) {
        this.cluster.operationLog.push({
            dbName: this.dbName,
            collection: this.name,
            op,
            filter: filter ? JSON.parse(JSON.stringify(filter)) : null,
        });
    }

    async createIndex(keys, options = {}) {
        this.indexes.push({ keys, options });
        return "ok";
    }

    async countDocuments(query = {}) {
        this._record("countDocuments", query);
        return this.docs.filter((d) => matchesQuery(d, query)).length;
    }

    async findOne(query = {}, options = {}) {
        this._record("findOne", query);
        const found = this.docs.find((d) => matchesQuery(d, query)) || null;
        return applyProjection(found, options.projection);
    }

    find(query = {}, options = {}) {
        this._record("find", query);
        let results = this.docs
            .filter((d) => matchesQuery(d, query))
            .map((d) => applyProjection(d, options.projection));

        const cursor = {
            sort: (sortSpec) => {
                const entries = Object.entries(sortSpec || {});
                results.sort((a, b) => {
                    for (const [field, dir] of entries) {
                        const va = a[field] ?? "";
                        const vb = b[field] ?? "";
                        if (va < vb) return -1 * dir;
                        if (va > vb) return 1 * dir;
                    }
                    return 0;
                });
                return cursor;
            },
            skip: (n) => {
                results = results.slice(n);
                return cursor;
            },
            limit: (n) => {
                results = results.slice(0, n);
                return cursor;
            },
            toArray: async () => results,
        };
        return cursor;
    }

    aggregate(pipeline = []) {
        const matchStage = pipeline.find((s) => s.$match);
        const matchFilter = matchStage ? matchStage.$match : {};
        this._record("aggregate", matchFilter);

        const matched = this.docs.filter((d) => matchesQuery(d, matchFilter));
        const byDocId = new Map();
        for (const chunk of matched) {
            const id = chunk.doc_id;
            if (!byDocId.has(id)) {
                byDocId.set(id, []);
            }
            byDocId.get(id).push(chunk);
        }

        const grouped = [];
        for (const [docId, items] of byDocId.entries()) {
            items.sort((a, b) => (a.chunk_index ?? 0) - (b.chunk_index ?? 0));
            const totalChars = items.reduce(
                (acc, c) => acc + String(c.text || "").length,
                0
            );
            grouped.push({
                _id: docId,
                chunk_count: items.length,
                created_at: items[items.length - 1]?.created_at || null,
                format: items[0]?.format || null,
                sample_text: items[0]?.text || "",
                total_chars: totalChars,
            });
        }
        grouped.sort((a, b) => String(a._id).localeCompare(String(b._id)));

        return {
            toArray: async () => grouped,
        };
    }

    async insertOne(doc) {
        this._record("insertOne", {
            tenant_id: doc.tenant_id,
            email: doc.email,
        });

        if (this.cluster.failNextInsertOnCollection === this.name) {
            this.cluster.failNextInsertOnCollection = null;
            const err = new Error("Simulated database insert failure");
            err.code = 11000;
            throw err;
        }

        // Enforce unique indexes for email / tenant_id / user_id / ticket_id / session_id_hash
        for (const idx of this.indexes) {
            if (idx.options?.unique) {
                const keyField = Object.keys(idx.keys)[0];
                if (
                    doc[keyField] !== undefined &&
                    this.docs.some((d) => d[keyField] === doc[keyField])
                ) {
                    const err = new Error(`Duplicate key error on ${keyField}`);
                    err.code = 11000;
                    throw err;
                }
            }
        }

        const copy = JSON.parse(JSON.stringify(doc));
        if (!copy._id) {
            copy._id = `id_${this.docs.length + 1}_${Date.now()}`;
        }
        this.docs.push(copy);
        return { insertedId: copy._id };
    }

    async updateOne(filter, update, options = {}) {
        this._record("updateOne", filter);
        const existingIdx = this.docs.findIndex((d) =>
            matchesQuery(d, filter)
        );

        if (existingIdx === -1) {
            if (options.upsert) {
                const newDoc = {};
                for (const [k, v] of Object.entries(filter)) {
                    if (!k.startsWith("$") && typeof v !== "object") {
                        newDoc[k] = v;
                    }
                }
                if (update.$setOnInsert) {
                    Object.assign(
                        newDoc,
                        JSON.parse(JSON.stringify(update.$setOnInsert))
                    );
                }
                if (update.$set) {
                    for (const [k, v] of Object.entries(update.$set)) {
                        setNestedValue(newDoc, k, v);
                    }
                }
                newDoc._id = `id_${this.docs.length + 1}_${Date.now()}`;
                this.docs.push(newDoc);
                return { matchedCount: 0, modifiedCount: 0, upsertedCount: 1 };
            }
            return { matchedCount: 0, modifiedCount: 0, upsertedCount: 0 };
        }

        const target = this.docs[existingIdx];
        if (update.$set) {
            for (const [k, v] of Object.entries(update.$set)) {
                setNestedValue(target, k, v);
            }
        }
        if (update.$unset) {
            for (const k of Object.keys(update.$unset)) {
                delete target[k];
            }
        }
        return { matchedCount: 1, modifiedCount: 1, upsertedCount: 0 };
    }

    async updateMany(filter, update) {
        this._record("updateMany", filter);
        let modified = 0;
        for (const doc of this.docs) {
            if (matchesQuery(doc, filter)) {
                if (update.$set) {
                    for (const [k, v] of Object.entries(update.$set)) {
                        setNestedValue(doc, k, v);
                    }
                }
                if (update.$unset) {
                    for (const k of Object.keys(update.$unset)) {
                        delete doc[k];
                    }
                }
                modified++;
            }
        }
        return { modifiedCount: modified };
    }

    async findOneAndUpdate(filter, update, options = {}) {
        this._record("findOneAndUpdate", filter);
        const idx = this.docs.findIndex((d) => matchesQuery(d, filter));
        if (idx === -1) return null;

        const target = this.docs[idx];
        if (update.$set) {
            for (const [k, v] of Object.entries(update.$set)) {
                setNestedValue(target, k, v);
            }
        }
        if (update.$push) {
            for (const [k, v] of Object.entries(update.$push)) {
                if (!Array.isArray(target[k])) target[k] = [];
                if (v && typeof v === "object" && Array.isArray(v.$each)) {
                    target[k].push(...v.$each);
                } else {
                    target[k].push(v);
                }
            }
        }
        return applyProjection(target, options.projection);
    }

    async deleteOne(filter) {
        this._record("deleteOne", filter);
        const idx = this.docs.findIndex((d) => matchesQuery(d, filter));
        if (idx === -1) return { deletedCount: 0 };
        this.docs.splice(idx, 1);
        return { deletedCount: 1 };
    }
}

class InMemoryDatabase {
    constructor(databaseName, cluster) {
        this.databaseName = databaseName;
        this.cluster = cluster;
        this.collections = new Map();
    }

    collection(name) {
        if (!this.collections.has(name)) {
            this.collections.set(
                name,
                new InMemoryCollection(name, this.databaseName, this.cluster)
            );
        }
        return this.collections.get(name);
    }
}

function extractSessionCookie(response) {
    const setCookie = response.headers.get("set-cookie") || "";
    const match = setCookie.match(/capstone_session=([^;]+)/);
    return match ? `capstone_session=${match[1]}` : "";
}

async function startTestServer(app) {
    return new Promise((resolve) => {
        const server = app.listen(0, "127.0.0.1", () => {
            const { port } = server.address();
            resolve({
                server,
                baseUrl: `http://127.0.0.1:${port}`,
            });
        });
    });
}

describe("Sprint 4 Slice 4: Authentication, Mode Isolation & Tenant Authorization", () => {
    let cluster;
    let server;
    let baseUrl;
    let ingestionCalls;
    const savedEnv = { ...process.env };

    beforeEach(async () => {
        process.env.APP_MODE = "standard";
        process.env.MONGODB_DB_NAME = "standard_prod_db";
        process.env.MONGODB_TRAINING_DB_NAME = "training_sandbox_db";
        delete process.env.LOGIN_RATE_LIMIT_MAX;

        cluster = new InMemoryDatabaseCluster();
        setDatabaseAdapter(cluster);
        resetLoginRateLimiter();

        ingestionCalls = [];
        setIngestionRunner(async (params) => {
            // Verify uploaded file exists during worker execution
            assert.ok(fs.existsSync(params.filePath));
            ingestionCalls.push(params);
            return {
                status: "success",
                tenant_id: params.tenantId,
                doc_id: params.docId,
                format: "md",
                chunks_created: 3,
                db_name: params.dbName,
            };
        });

        await connectToDatabase(process.env);
        const app = createApp();
        const started = await startTestServer(app);
        server = started.server;
        baseUrl = started.baseUrl;
    });

    afterEach(async () => {
        if (server) {
            await new Promise((resolve) => server.close(resolve));
            server = null;
        }
        resetDatabaseAdapter();
        resetIngestionRunner();
        resetLoginRateLimiter();
        process.env = { ...savedEnv };
    });

    test("1. Mode & Database Configuration Validation (Fail Closed)", async () => {
        // Default APP_MODE is standard
        assert.equal(validateAppMode(undefined), "standard");
        assert.equal(validateAppMode(""), "standard");
        assert.equal(validateAppMode("standard"), "standard");
        assert.equal(validateAppMode("preset_training"), "preset_training");

        // Invalid APP_MODE fails closed
        assert.throws(
            () => validateAppMode("demo"),
            /Invalid APP_MODE/
        );
        assert.throws(
            () => validateAppMode("true"),
            /Invalid APP_MODE/
        );

        // preset_training without MONGODB_TRAINING_DB_NAME fails closed
        assert.throws(
            () =>
                resolveRuntimeConfig({
                    APP_MODE: "preset_training",
                    MONGODB_DB_NAME: "standard_db",
                    MONGODB_TRAINING_DB_NAME: "",
                }),
            /requires an explicit MONGODB_TRAINING_DB_NAME/
        );

        // Identical MONGODB_DB_NAME and MONGODB_TRAINING_DB_NAME fails closed
        assert.throws(
            () =>
                resolveRuntimeConfig({
                    APP_MODE: "preset_training",
                    MONGODB_DB_NAME: "same_db",
                    MONGODB_TRAINING_DB_NAME: "same_db",
                }),
            /must be distinct/
        );

        // Public health endpoint must not leak database name or credentials
        const healthRes = await fetch(`${baseUrl}/api/health`);
        assert.equal(healthRes.status, 200);
        const healthBody = await healthRes.json();
        assert.equal(healthBody.status, "ok");
        assert.equal(healthBody.app_mode, "standard");
        assert.equal(healthBody.database, undefined);
    });

    test("2. Standard Mode Isolation: Seeds Nothing, Hides Pre-Existing Preset Records, Rejects Demo-Login", async () => {
        const stdDb = cluster.getDbForName("standard_prod_db");
        assert.equal(stdDb.collection("businesses").docs.length, 0);
        assert.equal(stdDb.collection("ticket_logs").docs.length, 0);

        // Even if old seeded preset records exist in standard_prod_db, standard mode must exclude and reject them
        await stdDb.collection("businesses").insertOne({
            tenant_id: "iron_and_oak",
            name: "Iron & Oak Provision Co.",
            industry: "Outdoor Gear",
            contact_email: "support@ironandoak.com",
        });

        // Public auth config in standard mode disables demo_login and hides preset fixtures
        const cfgRes = await fetch(`${baseUrl}/api/auth/config`);
        const cfg = await cfgRes.json();
        assert.equal(cfg.app_mode, "standard");
        assert.equal(cfg.demo_login_enabled, false);
        assert.deepEqual(cfg.preset_tenants, []);

        // Direct curl/POST to /api/auth/demo-login in standard mode is rejected with 403
        cluster.clearOperationLog();
        const demoRes = await fetch(`${baseUrl}/api/auth/demo-login`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ tenant_id: "iron_and_oak" }),
        });
        assert.equal(demoRes.status, 403);
        assert.equal(cluster.getProtectedResourceOps().length, 0);

        // Signup attempting to claim a preset tenant_id or preset business name is rejected with 409
        const presetSignupRes = await fetch(`${baseUrl}/api/auth/signup`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                admin_name: "Intruder",
                email: "intruder@example.com",
                password: "Password123!",
                business_name: "Iron & Oak",
                industry: "Retail",
                contact_email: "intruder@example.com",
            }),
        });
        assert.equal(presetSignupRes.status, 409);

        // Valid standard signup creates tenant 'cascade_bikes'
        const signupRes = await fetch(`${baseUrl}/api/auth/signup`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                admin_name: "Alice Admin",
                email: "alice@cascadebikes.com",
                password: "StrongPassword123!",
                business_name: "Cascade Bikes",
                industry: "Cycling & Repair",
                contact_email: "support@cascadebikes.com",
            }),
        });
        assert.equal(signupRes.status, 201);
        const cookie = extractSessionCookie(signupRes);
        assert.ok(cookie);

        // GET /api/tenants returns ONLY cascade_bikes and never returns the seeded iron_and_oak record
        const tenantsRes = await fetch(`${baseUrl}/api/tenants`, {
            headers: { Cookie: cookie },
        });
        assert.equal(tenantsRes.status, 200);
        const tenants = await tenantsRes.json();
        assert.equal(tenants.length, 1);
        assert.equal(tenants[0].tenant_id, "cascade_bikes");

        // Requesting preset tenant config in standard mode is rejected with 403 without reading businesses
        cluster.clearOperationLog();
        const presetCfgRes = await fetch(
            `${baseUrl}/api/tenants/iron_and_oak/config`,
            {
                headers: { Cookie: cookie },
            }
        );
        assert.equal(presetCfgRes.status, 403);
        assert.equal(cluster.getProtectedResourceOps().length, 0);

        // Preset source-file fallback on disk is disabled in standard mode
        assert.equal(
            resolveSafePresetSourcePath("iron_and_oak", "CARE_GUIDE", "md"),
            null
        );
    });

    test("3. Protected Route Matrix: No Session, Forged, Expired, Revoked -> 401; Cross-Tenant -> 403/404 with Zero Side Effects", async () => {
        // Create Tenant A and Tenant B via signup
        const resA = await fetch(`${baseUrl}/api/auth/signup`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                admin_name: "Admin Alpha",
                email: "alpha@tenanta.com",
                password: "AlphaPassword123!",
                business_name: "Tenant Alpha",
                industry: "Software",
                contact_email: "help@tenanta.com",
            }),
        });
        assert.equal(resA.status, 201);
        const cookieA = extractSessionCookie(resA);
        const bodyA = await resA.json();
        const tenantA = bodyA.tenant.tenant_id;

        const resB = await fetch(`${baseUrl}/api/auth/signup`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                admin_name: "Admin Beta",
                email: "beta@tenantb.com",
                password: "BetaPassword123!",
                business_name: "Tenant Beta",
                industry: "Hardware",
                contact_email: "help@tenantb.com",
            }),
        });
        assert.equal(resB.status, 201);
        const cookieB = extractSessionCookie(resB);
        const bodyB = await resB.json();
        const tenantB = bodyB.tenant.tenant_id;

        // Seed a ticket for Tenant B so we can test cross-tenant PATCH /api/tickets/:ticketId
        const createTicketB = await fetch(
            `${baseUrl}/api/tenants/${tenantB}/tickets`,
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    Cookie: cookieB,
                },
                body: JSON.stringify({
                    ticket_id: "TKT-TB-9001",
                    question: "Tenant B private question?",
                    answer: "Tenant B private answer.",
                }),
            }
        );
        assert.equal(createTicketB.status, 201);

        // Create an expired session and a revoked session in admin_sessions
        const stdDb = cluster.getDbForName("standard_prod_db");
        const expiredRaw = "a".repeat(64);
        const revokedRaw = "b".repeat(64);
        const { hashSessionToken } = require("../src/middleware/auth");

        await stdDb.collection("admin_sessions").insertOne({
            session_id_hash: hashSessionToken(expiredRaw),
            user_id: bodyA.user.user_id,
            principal_type: "admin",
            tenant_id: tenantA,
            authorized_tenant_ids: [tenantA],
            app_mode: "standard",
            created_at: new Date(Date.now() - 86400000).toISOString(),
            expires_at: new Date(Date.now() - 3600000).toISOString(),
            revoked_at: null,
        });

        await stdDb.collection("admin_sessions").insertOne({
            session_id_hash: hashSessionToken(revokedRaw),
            user_id: bodyA.user.user_id,
            principal_type: "admin",
            tenant_id: tenantA,
            authorized_tenant_ids: [tenantA],
            app_mode: "standard",
            created_at: new Date(Date.now() - 3600000).toISOString(),
            expires_at: new Date(Date.now() + 3600000).toISOString(),
            revoked_at: new Date().toISOString(),
        });

        const invalidCookies = [
            { label: "no session", header: "" },
            { label: "malformed session", header: "capstone_session=not-hex" },
            {
                label: "forged unknown session",
                header: `capstone_session=${"f".repeat(64)}`,
            },
            {
                label: "expired session",
                header: `capstone_session=${expiredRaw}`,
            },
            {
                label: "revoked session",
                header: `capstone_session=${revokedRaw}`,
            },
        ];

        const protectedRoutes = [
            { method: "GET", path: "/api/auth/session" },
            { method: "POST", path: "/api/auth/logout" },
            { method: "GET", path: "/api/tenants" },
            { method: "GET", path: `/api/tenants/${tenantA}/config` },
            {
                method: "PUT",
                path: `/api/tenants/${tenantA}/config`,
                body: { name: "Tampered" },
            },
            {
                method: "POST",
                path: "/api/documents/upload",
                multipart: true,
                tenantId: tenantA,
            },
            { method: "GET", path: `/api/tenants/${tenantA}/documents` },
            {
                method: "GET",
                path: `/api/tenants/${tenantA}/documents/RETURN_POLICY`,
            },
            { method: "GET", path: `/api/tenants/${tenantA}/chunks` },
            { method: "GET", path: `/api/tenants/${tenantA}/tickets` },
            {
                method: "POST",
                path: `/api/tenants/${tenantA}/tickets`,
                body: { question: "Unauthorized?" },
            },
            {
                method: "POST",
                path: "/api/tickets",
                body: { tenant_id: tenantA, question: "Unauthorized?" },
            },
            {
                method: "PATCH",
                path: "/api/tickets/TKT-TB-9001",
                body: { status: "resolved" },
            },
        ];

        // 3A. Every protected route must return 401 for missing/forged/expired/revoked sessions
        // with zero protected DB reads/writes, zero worker invocations, and zero temp files left
        for (const cookieCase of invalidCookies) {
            for (const route of protectedRoutes) {
                cluster.clearOperationLog();
                const filesBefore = new Set(fs.readdirSync("/tmp/uploads"));

                let res;
                if (route.multipart) {
                    const form = new FormData();
                    form.append(
                        "file",
                        new Blob(["# Test\nContent"], { type: "text/markdown" }),
                        "policy.md"
                    );
                    form.append("tenant_id", route.tenantId);
                    res = await fetch(`${baseUrl}${route.path}`, {
                        method: "POST",
                        headers: cookieCase.header
                            ? { Cookie: cookieCase.header }
                            : {},
                        body: form,
                    });
                } else {
                    const headers = { "Content-Type": "application/json" };
                    if (cookieCase.header) headers.Cookie = cookieCase.header;
                    res = await fetch(`${baseUrl}${route.path}`, {
                        method: route.method,
                        headers,
                        body: route.body
                            ? JSON.stringify(route.body)
                            : undefined,
                    });
                }

                assert.equal(
                    res.status,
                    401,
                    `Expected 401 on ${route.method} ${route.path} with ${cookieCase.label}, got ${res.status}`
                );
                assert.equal(
                    cluster.getProtectedResourceOps().length,
                    0,
                    `Expected 0 protected DB ops on ${route.method} ${route.path} with ${cookieCase.label}`
                );
                assert.equal(ingestionCalls.length, 0);

                const filesAfter = fs.readdirSync("/tmp/uploads");
                const newFiles = filesAfter.filter((f) => !filesBefore.has(f));
                assert.equal(
                    newFiles.length,
                    0,
                    `Expected 0 persisted upload files on rejected upload (${cookieCase.label})`
                );
            }
        }

        // 3B. Cross-tenant requests using Tenant A's valid session targeting Tenant B must be rejected with 403
        // with zero protected DB reads/mutations or worker calls
        const crossTenantCases = [
            { method: "GET", path: `/api/tenants?tenant_id=${tenantB}` },
            { method: "GET", path: `/api/tenants/${tenantB}/config` },
            {
                method: "PUT",
                path: `/api/tenants/${tenantB}/config`,
                body: { name: "Hacked" },
            },
            {
                method: "PUT",
                path: `/api/tenants/${tenantA}/config`,
                body: { tenant_id: tenantB, name: "Conflicting Selector" },
            },
            {
                method: "POST",
                path: "/api/documents/upload",
                multipart: true,
                tenantId: tenantB,
            },
            { method: "GET", path: `/api/tenants/${tenantB}/documents` },
            {
                method: "GET",
                path: `/api/tenants/${tenantB}/documents/RETURN_POLICY`,
            },
            { method: "GET", path: `/api/tenants/${tenantB}/chunks` },
            { method: "GET", path: `/api/tenants/${tenantB}/tickets` },
            {
                method: "POST",
                path: `/api/tenants/${tenantB}/tickets`,
                body: { question: "Cross tenant ticket?" },
            },
            {
                method: "POST",
                path: "/api/tickets",
                body: { tenant_id: tenantB, question: "Cross tenant ticket?" },
            },
            {
                method: "PATCH",
                path: "/api/tickets/TKT-TB-9001",
                body: { tenant_id: tenantB, status: "resolved" },
            },
        ];

        for (const tc of crossTenantCases) {
            cluster.clearOperationLog();
            const filesBefore = new Set(fs.readdirSync("/tmp/uploads"));

            let res;
            if (tc.multipart) {
                const form = new FormData();
                form.append(
                    "file",
                    new Blob(["# Cross Tenant\nTest"], {
                        type: "text/markdown",
                    }),
                    "cross.md"
                );
                form.append("tenant_id", tc.tenantId);
                res = await fetch(`${baseUrl}${tc.path}`, {
                    method: "POST",
                    headers: { Cookie: cookieA },
                    body: form,
                });
            } else {
                res = await fetch(`${baseUrl}${tc.path}`, {
                    method: tc.method,
                    headers: {
                        "Content-Type": "application/json",
                        Cookie: cookieA,
                    },
                    body: tc.body ? JSON.stringify(tc.body) : undefined,
                });
            }

            assert.equal(
                res.status,
                403,
                `Expected 403 for cross-tenant ${tc.method} ${tc.path}, got ${res.status}`
            );
            assert.equal(
                cluster.getProtectedResourceOps().length,
                0,
                `Expected 0 protected DB ops for cross-tenant ${tc.method} ${tc.path}`
            );
            assert.equal(ingestionCalls.length, 0);

            const filesAfter = fs.readdirSync("/tmp/uploads");
            const newFiles = filesAfter.filter((f) => !filesBefore.has(f));
            assert.equal(newFiles.length, 0);
        }

        // 3C. ID-only PATCH /api/tickets/TKT-TB-9001 with Tenant A's session (and no body tenant_id)
        // must scope the MongoDB query by { ticket_id: 'TKT-TB-9001', tenant_id: tenantA } and return 404 without mutating Tenant B's ticket!
        cluster.clearOperationLog();
        const patchOtherTicketRes = await fetch(
            `${baseUrl}/api/tickets/TKT-TB-9001`,
            {
                method: "PATCH",
                headers: {
                    "Content-Type": "application/json",
                    Cookie: cookieA,
                },
                body: JSON.stringify({
                    status: "resolved",
                    admin_notes: "Attempted cross-tenant hijack",
                }),
            }
        );
        assert.equal(patchOtherTicketRes.status, 404);
        const ticketOps = cluster.operationLog.filter(
            (op) => op.collection === "ticket_logs"
        );
        assert.equal(ticketOps.length, 1);
        assert.deepEqual(ticketOps[0].filter, {
            ticket_id: "TKT-TB-9001",
            tenant_id: tenantA,
        });

        // Verify Tenant B's ticket in DB was NOT modified
        const untouchedTicket = await stdDb
            .collection("ticket_logs")
            .findOne({ ticket_id: "TKT-TB-9001" });
        assert.equal(untouchedTicket.status, "pending_review");
        assert.equal(untouchedTicket.admin_notes, "");
    });

    test("4. Valid Signup, Login, Password Hashing, Partial Failure Rollback, Same-Tenant CRUD & Logout Lifecycle", async () => {
        const stdDb = cluster.getDbForName("standard_prod_db");

        // 4A. Partial failure during signup rolls back businesses.insertOne so no orphan tenant remains
        cluster.failNextInsertOnCollection = "admin_users";
        const failedSignupRes = await fetch(`${baseUrl}/api/auth/signup`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                admin_name: "Orphan Test",
                email: "orphan@test.com",
                password: "Password123!",
                business_name: "Orphan Co",
                industry: "Testing",
                contact_email: "support@orphan.co",
            }),
        });
        assert.equal(failedSignupRes.status, 409);
        assert.equal(stdDb.collection("businesses").docs.length, 0);

        // 4B. Valid signup creates hashed password, default agent_config, and session
        const signupRes = await fetch(`${baseUrl}/api/auth/signup`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                admin_name: "Jordan Lee",
                email: "Jordan@PacificGear.com",
                password: "SecurePassword99!",
                business_name: "Pacific Gear Co",
                industry: "Outdoor Equipment",
                contact_email: "support@pacificgear.com",
            }),
        });
        assert.equal(signupRes.status, 201);
        const signupData = await signupRes.json();
        const signupCookie = extractSessionCookie(signupRes);

        assert.equal(signupData.user.email, "jordan@pacificgear.com");
        assert.equal(signupData.user.password_hash, undefined);
        assert.equal(signupData.tenant.tenant_id, "pacific_gear_co");
        assert.equal(signupData.tenant.agent_config.temperature, 0.2);
        assert.equal(signupData.tenant.agent_config.max_context_chunks, 4);
        assert.equal(signupData.tenant.agent_config.similarity_threshold, 0.7);

        // Verify password_hash in DB is a bcrypt hash and not plaintext
        const storedUser = stdDb.collection("admin_users").docs[0];
        assert.ok(storedUser.password_hash.startsWith("$2"));
        assert.notEqual(storedUser.password_hash, "SecurePassword99!");

        // 4C. Duplicate business name signup allocates a unique tenant_id and never attaches to pacific_gear_co
        const dupNameSignup = await fetch(`${baseUrl}/api/auth/signup`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                admin_name: "Other Owner",
                email: "owner2@otherpacific.com",
                password: "SecurePassword99!",
                business_name: "Pacific Gear Co",
                industry: "Outdoor Equipment",
                contact_email: "info@otherpacific.com",
            }),
        });
        assert.equal(dupNameSignup.status, 201);
        const dupNameData = await dupNameSignup.json();
        assert.notEqual(dupNameData.tenant.tenant_id, "pacific_gear_co");
        assert.ok(dupNameData.tenant.tenant_id.startsWith("pacific_gear_co_"));

        // 4D. Same-tenant config update, document upload, and ticket CRUD using Jordan's session
        const updateCfgRes = await fetch(
            `${baseUrl}/api/tenants/pacific_gear_co/config`,
            {
                method: "PUT",
                headers: {
                    "Content-Type": "application/json",
                    Cookie: signupCookie,
                },
                body: JSON.stringify({
                    agent_config: {
                        temperature: 0.35,
                        similarity_threshold: 0.78,
                    },
                }),
            }
        );
        assert.equal(updateCfgRes.status, 200);
        const updatedCfg = await updateCfgRes.json();
        assert.equal(updatedCfg.agent_config.temperature, 0.35);

        // Upload document -> worker receives session tenant and active standard database name
        const form = new FormData();
        form.append(
            "file",
            new Blob(["# Warranty\nLifetime guarantee."], {
                type: "text/markdown",
            }),
            "WARRANTY_POLICY.md"
        );
        form.append("tenant_id", "pacific_gear_co");

        const uploadRes = await fetch(`${baseUrl}/api/documents/upload`, {
            method: "POST",
            headers: { Cookie: signupCookie },
            body: form,
        });
        assert.equal(uploadRes.status, 200);
        assert.equal(ingestionCalls.length, 1);
        assert.equal(ingestionCalls[0].tenantId, "pacific_gear_co");
        assert.equal(ingestionCalls[0].dbName, "standard_prod_db");

        // Logout revokes session and prevents reuse
        const logoutRes = await fetch(`${baseUrl}/api/auth/logout`, {
            method: "POST",
            headers: { Cookie: signupCookie },
        });
        assert.equal(logoutRes.status, 200);

        const reuseRes = await fetch(`${baseUrl}/api/auth/session`, {
            headers: { Cookie: signupCookie },
        });
        assert.equal(reuseRes.status, 401);

        // Re-login with email + password succeeds
        const loginRes = await fetch(`${baseUrl}/api/auth/login`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                email: "jordan@pacificgear.com",
                password: "SecurePassword99!",
            }),
        });
        assert.equal(loginRes.status, 200);
        const loginData = await loginRes.json();
        assert.equal(loginData.user.tenant_id, "pacific_gear_co");
        assert.equal(loginData.user.password_hash, undefined);
    });

    test("5. Preset Training Mode: Demo-Login, Preset Isolation, Session Revocation on Switch & Mode Tampering", async () => {
        // Switch environment to preset_training
        process.env.APP_MODE = "preset_training";
        process.env.MONGODB_DB_NAME = "standard_prod_db";
        process.env.MONGODB_TRAINING_DB_NAME = "training_sandbox_db";

        await connectToDatabase(process.env);
        const trainingDb = cluster.getDbForName("training_sandbox_db");

        // Verify training DB was seeded with the 5 preset tenants and 12 tickets, while standard_prod_db remains untouched
        assert.equal(trainingDb.collection("businesses").docs.length, 5);
        assert.equal(trainingDb.collection("ticket_logs").docs.length, 12);
        assert.equal(
            cluster.getDbForName("standard_prod_db").collection("businesses")
                .docs.length,
            0
        );

        // Public auth config in preset_training mode exposes public fixture labels only
        const cfgRes = await fetch(`${baseUrl}/api/auth/config`);
        const cfg = await cfgRes.json();
        assert.equal(cfg.app_mode, "preset_training");
        assert.equal(cfg.demo_login_enabled, true);
        assert.equal(cfg.preset_tenants.length, 5);
        assert.equal(cfg.preset_tenants[0].agent_config, undefined);

        // Demo-login rejects unknown / non-preset tenant IDs
        const badPresetRes = await fetch(`${baseUrl}/api/auth/demo-login`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ tenant_id: "custom_standard_tenant" }),
        });
        assert.equal(badPresetRes.status, 403);

        // Demo-login rejects attempts to pass email/password/user_id
        const impersonateRes = await fetch(`${baseUrl}/api/auth/demo-login`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                tenant_id: "iron_and_oak",
                email: "admin@ironandoak.com",
            }),
        });
        assert.equal(impersonateRes.status, 400);

        // Valid one-click demo-login for iron_and_oak
        const demoIoRes = await fetch(`${baseUrl}/api/auth/demo-login`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ tenant_id: "iron_and_oak" }),
        });
        assert.equal(demoIoRes.status, 200);
        const ioCookie = extractSessionCookie(demoIoRes);
        const ioBody = await demoIoRes.json();
        assert.equal(ioBody.user.principal_type, "demo_preset");
        assert.equal(ioBody.user.tenant_id, "iron_and_oak");

        // Demo session for iron_and_oak cannot access harbor_view directly
        cluster.clearOperationLog();
        const crossPresetRes = await fetch(
            `${baseUrl}/api/tenants/harbor_view/tickets`,
            {
                headers: { Cookie: ioCookie },
            }
        );
        assert.equal(crossPresetRes.status, 403);
        assert.equal(cluster.getProtectedResourceOps().length, 0);

        // Upload in preset_training mode passes training_sandbox_db to Python worker
        const form = new FormData();
        form.append(
            "file",
            new Blob(["# Field Care\nWax instructions."], {
                type: "text/markdown",
            }),
            "FIELD_CARE.md"
        );
        form.append("tenant_id", "iron_and_oak");
        const uploadRes = await fetch(`${baseUrl}/api/documents/upload`, {
            method: "POST",
            headers: { Cookie: ioCookie },
            body: form,
        });
        assert.equal(uploadRes.status, 200);
        assert.equal(ingestionCalls.length, 1);
        assert.equal(ingestionCalls[0].tenantId, "iron_and_oak");
        assert.equal(ingestionCalls[0].dbName, "training_sandbox_db");

        // Switching preset via demo-login revokes the old iron_and_oak session and issues a harbor_view session
        const switchHvRes = await fetch(`${baseUrl}/api/auth/demo-login`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                Cookie: ioCookie,
            },
            body: JSON.stringify({ tenant_id: "harbor_view" }),
        });
        assert.equal(switchHvRes.status, 200);
        const hvCookie = extractSessionCookie(switchHvRes);

        // Old iron_and_oak session cookie is now revoked (401)
        const oldCookieRes = await fetch(
            `${baseUrl}/api/tenants/iron_and_oak/config`,
            {
                headers: { Cookie: ioCookie },
            }
        );
        assert.equal(oldCookieRes.status, 401);

        // New harbor_view session cookie works for harbor_view
        const hvTicketsRes = await fetch(
            `${baseUrl}/api/tenants/harbor_view/tickets`,
            {
                headers: { Cookie: hvCookie },
            }
        );
        assert.equal(hvTicketsRes.status, 200);
        const hvTickets = await hvTicketsRes.json();
        assert.ok(hvTickets.length > 0);
        assert.ok(hvTickets.every((t) => t.tenant_id === "harbor_view"));

        // Mode tampering: if server switches back to standard mode, the demo session is immediately rejected (401)
        process.env.APP_MODE = "standard";
        const modeMismatchRes = await fetch(`${baseUrl}/api/auth/session`, {
            headers: { Cookie: hvCookie },
        });
        assert.equal(modeMismatchRes.status, 401);
    });

    test("6. CSRF Origin Protection & Bounded Login Rate Limiting", async () => {
        // Cross-origin POST with untrusted Origin is blocked with 403 before route execution
        const csrfRes = await fetch(`${baseUrl}/api/auth/signup`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                Origin: "https://evil-attacker.example",
            },
            body: JSON.stringify({
                admin_name: "Attacker",
                email: "attacker@evil.example",
                password: "Password123!",
                business_name: "Evil Co",
                industry: "Malware",
                contact_email: "attacker@evil.example",
            }),
        });
        assert.equal(csrfRes.status, 403);

        // Sec-Fetch-Site: cross-site is blocked with 403
        const secFetchRes = await fetch(`${baseUrl}/api/auth/login`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Sec-Fetch-Site": "cross-site",
            },
            body: JSON.stringify({
                email: "user@example.com",
                password: "Password123!",
            }),
        });
        assert.equal(secFetchRes.status, 403);

        // Bounded login rate limiter returns 429 after max failed attempts
        process.env.LOGIN_RATE_LIMIT_MAX = "3";
        for (let i = 0; i < 3; i++) {
            const failRes = await fetch(`${baseUrl}/api/auth/login`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    email: "target@company.com",
                    password: "WrongPassword!",
                }),
            });
            assert.equal(failRes.status, 401);
        }

        const limitedRes = await fetch(`${baseUrl}/api/auth/login`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                email: "target@company.com",
                password: "WrongPassword!",
            }),
        });
        assert.equal(limitedRes.status, 429);
    });

    test("7. Slice 5: Canonical Fixture Manifest, Custom Session Cookie & Upload Staging Isolation, and Health Readiness", async () => {
        process.env.APP_MODE = "preset_training";
        process.env.MONGODB_DB_NAME = "standard_prod_db";
        process.env.MONGODB_TRAINING_DB_NAME = "training_sandbox_db";
        process.env.SESSION_COOKIE_NAME = "capstone_demo_session";
        process.env.UPLOAD_STAGING_DIR = "/tmp/capstone_test_demo_uploads";

        await connectToDatabase(process.env);

        // 7A. Demo login issues custom cookie name capstone_demo_session (does not collide with capstone_session)
        const demoRes = await fetch(`${baseUrl}/api/auth/demo-login`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ tenant_id: "cinder_and_salt" }),
        });
        assert.equal(demoRes.status, 200);
        const setCookieHeader = demoRes.headers.get("set-cookie") || "";
        assert.ok(
            setCookieHeader.startsWith("capstone_demo_session="),
            `Expected capstone_demo_session cookie, got ${setCookieHeader}`
        );

        // Standard capstone_session cookie is ignored when SESSION_COOKIE_NAME=capstone_demo_session
        const rawCookieValue = setCookieHeader.split(";")[0].split("=")[1];
        const wrongCookieNameRes = await fetch(`${baseUrl}/api/auth/session`, {
            headers: { Cookie: `capstone_session=${rawCookieValue}` },
        });
        assert.equal(wrongCookieNameRes.status, 401);

        const rightCookieNameRes = await fetch(`${baseUrl}/api/auth/session`, {
            headers: { Cookie: `capstone_demo_session=${rawCookieValue}` },
        });
        assert.equal(rightCookieNameRes.status, 200);

        // 7B. Health check reports database_ready, vector_index_ready, ollama_ready without exposing DB names or URIs
        const healthRes = await fetch(`${baseUrl}/api/health`);
        assert.equal(healthRes.status, 200);
        const healthBody = await healthRes.json();
        assert.equal(healthBody.status, "ok");
        assert.equal(healthBody.app_mode, "preset_training");
        assert.equal(healthBody.database_ready, true);
        assert.equal(typeof healthBody.vector_index_ready, "boolean");
        assert.equal(typeof healthBody.ollama_reachable, "boolean");
        assert.equal(typeof healthBody.ollama_ready, "boolean");
        assert.equal(typeof healthBody.model_requested, "string");
        const serializedHealth = JSON.stringify(healthBody).toLowerCase();
        assert.ok(!serializedHealth.includes("training_sandbox_db"));
        assert.ok(!serializedHealth.includes("standard_prod_db"));
        assert.ok(!serializedHealth.includes("mongodb"));

        delete process.env.SESSION_COOKIE_NAME;
        delete process.env.UPLOAD_STAGING_DIR;
    });
});

