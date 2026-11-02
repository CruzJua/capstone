const { test, describe, beforeEach, afterEach } = require("node:test");
const assert = require("node:assert/strict");
const { createApp } = require("../src/server");
const {
    connectToDatabase,
    setDatabaseAdapter,
    resetDatabaseAdapter,
} = require("../src/db/mongo");
const { resetLoginRateLimiter } = require("../src/routes/auth");
const { hashSessionToken } = require("../src/middleware/auth");

function extractSessionCookie(response) {
    const setCookie = response.headers.get("set-cookie") || "";
    const match = setCookie.match(/capstone_session=([^;]+)/);
    return match ? `capstone_session=${match[1]}` : "";
}

function extractRawToken(cookieHeader) {
    const match = String(cookieHeader || "").match(/capstone_session=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
}

describe("Sprint 4 Slice 4: Session Lifecycle, Account Switching & Client Guard Flows", () => {
    let server;
    let baseUrl;
    let dbDocs;
    const savedEnv = { ...process.env };

    beforeEach(async () => {
        process.env.APP_MODE = "standard";
        process.env.MONGODB_DB_NAME = "standard_flow_db";
        process.env.MONGODB_TRAINING_DB_NAME = "training_flow_db";
        resetLoginRateLimiter();

        dbDocs = {
            businesses: [],
            admin_users: [],
            admin_sessions: [],
            doc_vectors: [],
            ticket_logs: [],
        };

        const mockDb = {
            databaseName: "standard_flow_db",
            collection: (name) => ({
                createIndex: async () => "ok",
                countDocuments: async () => (dbDocs[name] || []).length,
                findOne: async (query = {}, options = {}) => {
                    const list = dbDocs[name] || [];
                    const found =
                        list.find((doc) =>
                            Object.entries(query).every(
                                ([k, v]) => doc[k] === v
                            )
                        ) || null;
                    if (!found) return null;
                    const copy = { ...found };
                    if (options.projection) {
                        for (const [f, flag] of Object.entries(
                            options.projection
                        )) {
                            if (flag === 0) delete copy[f];
                        }
                    }
                    return copy;
                },
                find: (query = {}, options = {}) => {
                    const list = (dbDocs[name] || []).filter((doc) => {
                        if (query.tenant_id && typeof query.tenant_id === "object") {
                            const inArr = query.tenant_id.$in || [];
                            const ninArr = query.tenant_id.$nin || [];
                            if (!inArr.includes(doc.tenant_id)) return false;
                            if (ninArr.includes(doc.tenant_id)) return false;
                            return true;
                        }
                        return Object.entries(query).every(
                            ([k, v]) => doc[k] === v
                        );
                    });
                    const projected = list.map((d) => {
                        const copy = { ...d };
                        if (options.projection) {
                            for (const [f, flag] of Object.entries(
                                options.projection
                            )) {
                                if (flag === 0) delete copy[f];
                            }
                        }
                        return copy;
                    });
                    const cursor = {
                        sort: () => cursor,
                        skip: () => cursor,
                        limit: () => cursor,
                        toArray: async () => projected,
                    };
                    return cursor;
                },
                insertOne: async (doc) => {
                    const copy = { ...doc, _id: `id_${Date.now()}_${Math.random()}` };
                    dbDocs[name].push(copy);
                    return { insertedId: copy._id };
                },
                updateOne: async (filter, update, options = {}) => {
                    const idx = dbDocs[name].findIndex((d) =>
                        Object.entries(filter).every(([k, v]) => {
                            if (typeof v === "object" && v !== null && "$exists" in v) {
                                return (d[k] !== undefined) === Boolean(v.$exists);
                            }
                            return d[k] === v;
                        })
                    );
                    if (idx === -1) {
                        if (options.upsert) {
                            const created = {
                                ...(update.$setOnInsert || {}),
                                ...(update.$set || {}),
                            };
                            dbDocs[name].push(created);
                            return { modifiedCount: 0, upsertedCount: 1 };
                        }
                        return { modifiedCount: 0 };
                    }
                    if (update.$set) {
                        Object.assign(dbDocs[name][idx], update.$set);
                    }
                    return { modifiedCount: 1 };
                },
                updateMany: async () => ({ modifiedCount: 0 }),
                deleteOne: async (filter) => {
                    const idx = dbDocs[name].findIndex((d) =>
                        Object.entries(filter).every(([k, v]) => d[k] === v)
                    );
                    if (idx !== -1) dbDocs[name].splice(idx, 1);
                    return { deletedCount: idx !== -1 ? 1 : 0 };
                },
            }),
        };

        setDatabaseAdapter(mockDb);
        await connectToDatabase(process.env);
        const app = createApp();
        await new Promise((resolve) => {
            server = app.listen(0, "127.0.0.1", () => {
                baseUrl = `http://127.0.0.1:${server.address().port}`;
                resolve();
            });
        });
    });

    afterEach(async () => {
        if (server) {
            await new Promise((resolve) => server.close(resolve));
            server = null;
        }
        resetDatabaseAdapter();
        resetLoginRateLimiter();
        process.env = { ...savedEnv };
    });

    test("1. Login Failure Non-Disclosure, Session Restoration, Account Switching & Expiration", async () => {
        // Signup Account 1 (Summit Gear)
        const s1 = await fetch(`${baseUrl}/api/auth/signup`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                admin_name: "Sam Summit",
                email: "sam@summit.com",
                password: "SummitPassword1!",
                business_name: "Summit Gear",
                industry: "Outdoor",
                contact_email: "support@summit.com",
            }),
        });
        assert.equal(s1.status, 201);
        const cookie1 = extractSessionCookie(s1);

        // Signup Account 2 (Valley Bakery)
        const s2 = await fetch(`${baseUrl}/api/auth/signup`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                admin_name: "Val Valley",
                email: "val@valley.com",
                password: "ValleyPassword2!",
                business_name: "Valley Bakery",
                industry: "Food",
                contact_email: "support@valley.com",
            }),
        });
        assert.equal(s2.status, 201);

        // Login failure for non-existent email vs wrong password returns identical status and error message
        const unknownEmailLogin = await fetch(`${baseUrl}/api/auth/login`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                email: "nobody@nowhere.com",
                password: "WrongPassword1!",
            }),
        });
        const wrongPassLogin = await fetch(`${baseUrl}/api/auth/login`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                email: "sam@summit.com",
                password: "WrongPassword1!",
            }),
        });
        assert.equal(unknownEmailLogin.status, 401);
        assert.equal(wrongPassLogin.status, 401);
        const err1 = await unknownEmailLogin.json();
        const err2 = await wrongPassLogin.json();
        assert.equal(err1.error, "Invalid email or password.");
        assert.equal(err2.error, "Invalid email or password.");

        // Restoring session with cookie1 returns Sam's profile and ONLY summit_gear
        const restoreRes = await fetch(`${baseUrl}/api/auth/session`, {
            headers: { Cookie: cookie1 },
        });
        assert.equal(restoreRes.status, 200);
        const restored = await restoreRes.json();
        assert.equal(restored.authenticated, true);
        assert.equal(restored.user.email, "sam@summit.com");
        assert.equal(restored.authorized_tenants.length, 1);
        assert.equal(restored.authorized_tenants[0].tenant_id, "summit_gear");

        // Account switching: Logging in as Val while sending Sam's cookie1 revokes cookie1 and issues cookie2 for valley_bakery
        const switchLoginRes = await fetch(`${baseUrl}/api/auth/login`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                Cookie: cookie1,
            },
            body: JSON.stringify({
                email: "val@valley.com",
                password: "ValleyPassword2!",
            }),
        });
        assert.equal(switchLoginRes.status, 200);
        const cookie2 = extractSessionCookie(switchLoginRes);
        assert.notEqual(cookie2, cookie1);

        // Old cookie1 is now revoked and cannot access /api/auth/session or /api/tenants
        const oldSessionCheck = await fetch(`${baseUrl}/api/auth/session`, {
            headers: { Cookie: cookie1 },
        });
        assert.equal(oldSessionCheck.status, 401);

        // New cookie2 only sees valley_bakery and cannot access summit_gear even if localStorage had summit_gear
        const valTenantsRes = await fetch(`${baseUrl}/api/tenants`, {
            headers: { Cookie: cookie2 },
        });
        assert.equal(valTenantsRes.status, 200);
        const valTenants = await valTenantsRes.json();
        assert.equal(valTenants.length, 1);
        assert.equal(valTenants[0].tenant_id, "valley_bakery");

        const staleStorageAttempt = await fetch(
            `${baseUrl}/api/tenants/summit_gear/config`,
            {
                headers: { Cookie: cookie2 },
            }
        );
        assert.equal(staleStorageAttempt.status, 403);

        // Simulate session expiration on cookie2 in the database
        const rawToken2 = extractRawToken(cookie2);
        const hash2 = hashSessionToken(rawToken2);
        const sessionDoc = dbDocs.admin_sessions.find(
            (s) => s.session_id_hash === hash2
        );
        sessionDoc.expires_at = new Date(Date.now() - 1000).toISOString();

        const expiredCheck = await fetch(`${baseUrl}/api/auth/session`, {
            headers: { Cookie: cookie2 },
        });
        assert.equal(expiredCheck.status, 401);
        const clearHeader = expiredCheck.headers.get("set-cookie") || "";
        assert.ok(clearHeader.includes("Max-Age=0"));
    });
});

