const { test, describe, beforeEach, afterEach } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { createApp } = require("../src/server");
const { setDatabaseAdapter, resetDatabaseAdapter } = require("../src/db/mongo");
const { PRESET_TENANTS } = require("../src/config/presets");
const {
    buildVectorIndexDefinition,
    classifyIndex,
    ensureVectorIndex,
    getLastVectorIndexSetup,
    getVectorIndexStatus,
    monitorVectorIndex,
    resetVectorIndexState,
    startVectorIndexSetup,
} = require("../src/db/vectorIndex");

const BASE_COLLECTIONS = ["businesses", "ticket_logs", "admin_users", "admin_sessions"];

function driverError(message, extra = {}) {
    return Object.assign(new Error(message), extra);
}
const permissionError = () =>
    driverError("not authorized on example_db to execute command { createSearchIndexes: ... }", {
        code: 13,
        codeName: "Unauthorized",
    });

/**
 * A mocked MongoDB database (driver surface only). It records every call so tests can assert that an
 * index is created exactly once. No network, and never a real database.
 */
function makeMockDb(options = {}) {
    const state = {
        collections: new Set(options.collections ?? [...BASE_COLLECTIONS, "doc_vectors"]),
        indexes: [...(options.indexes ?? [])],
        createdCollections: [],
        createdIndexes: [],
        listSearchIndexCalls: 0,
        listCollectionCalls: 0,
    };
    const db = {
        state,
        listCollections: () => ({
            toArray: async () => {
                state.listCollectionCalls += 1;
                if (options.listCollectionsError) throw options.listCollectionsError;
                return [...state.collections].map((name) => ({ name }));
            },
        }),
        createCollection: async (name) => {
            state.createdCollections.push(name);
            if (options.createCollectionError) throw options.createCollectionError;
            state.collections.add(name);
        },
        collection: () => ({
            countDocuments: async () => {
                if (options.countError) throw options.countError;
                return 0;
            },
            ...(options.noSearchSupport
                ? {}
                : {
                      listSearchIndexes: (name) => ({
                          toArray: async () => {
                              state.listSearchIndexCalls += 1;
                              if (options.listError) throw options.listError;
                              return state.indexes.filter((index) => !name || index.name === name);
                          },
                      }),
                  }),
            createSearchIndex: async (model) => {
                state.createdIndexes.push(model);
                if (options.createError) throw options.createError;
                state.indexes.push({
                    name: model.name,
                    status: "PENDING",
                    queryable: false,
                    latestDefinition: model.definition,
                });
                return model.name;
            },
        }),
    };
    return db;
}

const readyIndex = (extra = {}) => ({
    name: "vector_index",
    status: "READY",
    queryable: true,
    latestDefinition: buildVectorIndexDefinition(384),
    ...extra,
});

function silentLogger() {
    const lines = { log: [], warn: [], error: [] };
    return {
        lines,
        log: (line) => lines.log.push(line),
        warn: (line) => lines.warn.push(line),
        error: (line) => lines.error.push(line),
    };
}

describe("vector index setup (mocked driver, no real database)", () => {
    const savedEnv = { ...process.env };
    let db;

    function useDb(options) {
        db = makeMockDb(options);
        setDatabaseAdapter(db);
        return db;
    }

    beforeEach(() => {
        process.env.APP_MODE = "standard";
        process.env.MONGODB_DB_NAME = "vector_setup_test_db";
        delete process.env.MONGODB_TRAINING_DB_NAME;
        for (const key of [
            "MONGODB_VECTOR_INDEX_NAME",
            "MONGODB_COLLECTION_NAME",
            "VECTOR_INDEX_DIMENSIONS",
            "VECTOR_INDEX_AUTO_SETUP",
        ]) {
            delete process.env[key];
        }
        resetVectorIndexState();
    });

    afterEach(() => {
        resetDatabaseAdapter();
        resetVectorIndexState();
        for (const key of Object.keys(process.env)) {
            if (!(key in savedEnv)) delete process.env[key];
        }
        Object.assign(process.env, savedEnv);
    });

    describe("ensureVectorIndex", () => {
        test("index absent -> created exactly once, even across repeated runs", async () => {
            useDb();
            const first = await ensureVectorIndex();
            assert.equal(first.state, "building");
            assert.equal(first.index_created, true);
            assert.equal(db.state.createdIndexes.length, 1);

            const second = await ensureVectorIndex();
            const third = await ensureVectorIndex();
            assert.equal(second.index_created, false);
            assert.equal(third.index_created, false);
            assert.equal(db.state.createdIndexes.length, 1, "an existing index must not be created again");
        });

        test("creates the shared definition: cosine vector plus tenant_id and doc_id filters", async () => {
            useDb();
            await ensureVectorIndex();
            const [model] = db.state.createdIndexes;
            assert.equal(model.name, "vector_index");
            assert.equal(model.type, "vectorSearch");
            assert.deepEqual(model.definition, {
                fields: [
                    { type: "vector", path: "embedding", numDimensions: 384, similarity: "cosine" },
                    { type: "filter", path: "tenant_id" },
                    { type: "filter", path: "doc_id" },
                ],
            });
        });

        test("index present and ready -> nothing is created", async () => {
            useDb({ indexes: [readyIndex()] });
            const result = await ensureVectorIndex();
            assert.equal(result.state, "ready");
            assert.equal(result.index_created, false);
            assert.equal(db.state.createdIndexes.length, 0);
            assert.equal(db.state.createdCollections.length, 0);
        });

        test("index present but still building -> not recreated", async () => {
            useDb({ indexes: [{ name: "vector_index", status: "BUILDING", queryable: false }] });
            const result = await ensureVectorIndex();
            assert.equal(result.state, "building");
            assert.equal(result.index_created, false);
            assert.equal(db.state.createdIndexes.length, 0);
        });

        test("a failed or wrongly sized existing index is reported, never dropped or recreated", async () => {
            useDb({ indexes: [{ name: "vector_index", status: "FAILED", queryable: false }] });
            assert.equal((await ensureVectorIndex()).state, "failed");
            assert.equal(db.state.createdIndexes.length, 0);

            useDb({ indexes: [readyIndex({ latestDefinition: buildVectorIndexDefinition(768) })] });
            const mismatch = await ensureVectorIndex();
            assert.equal(mismatch.state, "misconfigured");
            assert.match(mismatch.message, /768/);
            assert.equal(db.state.createdIndexes.length, 0);
        });

        test("missing collections are created once and the index follows", async () => {
            useDb({ collections: [] });
            const first = await ensureVectorIndex();
            assert.deepEqual([...first.collections_created].sort(), [...BASE_COLLECTIONS, "doc_vectors"].sort());
            assert.equal(db.state.createdIndexes.length, 1);

            const second = await ensureVectorIndex();
            assert.deepEqual(second.collections_created, []);
            assert.equal(db.state.createdCollections.length, BASE_COLLECTIONS.length + 1, "no collection created twice");
        });

        test("existing collections are left alone", async () => {
            useDb({ indexes: [readyIndex()] });
            await ensureVectorIndex();
            assert.deepEqual(db.state.createdCollections, []);
        });

        test("a concurrent creator is tolerated (duplicate index and collection errors)", async () => {
            useDb({ createError: driverError("Duplicate Index", { code: 68, codeName: "IndexAlreadyExists" }) });
            const result = await ensureVectorIndex();
            assert.equal(result.state, "building");
            assert.equal(result.index_created, false);

            useDb({
                collections: [],
                createCollectionError: driverError("Collection already exists", { code: 48, codeName: "NamespaceExists" }),
            });
            const raced = await ensureVectorIndex();
            assert.notEqual(raced.state, "permission_denied");
            assert.deepEqual(raced.collections_created, []);
        });

        test("a collection that does not exist yet reads as 'missing' and gets an index", async () => {
            useDb({ listError: driverError("ns not found", { code: 26, codeName: "NamespaceNotFound" }) });
            const result = await ensureVectorIndex();
            assert.equal(result.index_created, true);
            assert.equal(result.state, "building");
        });

        test("index name, collection name and dimensions come from the environment", async () => {
            process.env.MONGODB_VECTOR_INDEX_NAME = "custom_index";
            process.env.MONGODB_COLLECTION_NAME = "custom_vectors";
            process.env.VECTOR_INDEX_DIMENSIONS = "768";
            useDb({ collections: [] });
            await ensureVectorIndex();
            assert.equal(db.state.createdIndexes[0].name, "custom_index");
            assert.equal(db.state.createdIndexes[0].definition.fields[0].numDimensions, 768);
            assert.ok(db.state.createdCollections.includes("custom_vectors"));
        });

        test("records the attempt for /api/health", async () => {
            useDb();
            assert.equal(getLastVectorIndexSetup(), null);
            await ensureVectorIndex();
            const recorded = getLastVectorIndexSetup();
            assert.equal(recorded.state, "building");
            assert.ok(recorded.attempted_at);
        });
    });

    describe("permission errors", () => {
        const assertClearPermissionMessage = (result) => {
            assert.equal(result.state, "permission_denied");
            assert.equal(result.index_created, false);
            assert.match(result.message, /database user is not permitted/i);
            assert.match(result.message, /createSearchIndexes/);
            assert.match(result.message, /listSearchIndexes/);
            assert.ok(result.message.includes("vector_index"));
            assert.ok(!result.message.toLowerCase().includes("mongodb"));
            assert.ok(!result.message.includes("example_db"), "must not echo driver text or database names");
        };

        test("creating the index is not authorized", async () => {
            useDb({ createError: permissionError() });
            assertClearPermissionMessage(await ensureVectorIndex());
        });

        test("listing search indexes is not authorized", async () => {
            useDb({ listError: permissionError() });
            assertClearPermissionMessage(await ensureVectorIndex());
        });

        test("creating the vector collection is not authorized", async () => {
            useDb({ collections: BASE_COLLECTIONS, createCollectionError: permissionError() });
            const result = await ensureVectorIndex();
            assertClearPermissionMessage(result);
            assert.equal(db.state.createdIndexes.length, 0, "no index attempt after the collection failed");
        });

        test("Atlas style 'not allowed to do action' errors are recognised too", async () => {
            useDb({
                createError: driverError("user is not allowed to do action [createSearchIndexes] on [db.doc_vectors]", {
                    code: 8000,
                }),
            });
            assertClearPermissionMessage(await ensureVectorIndex());
        });

        test("never throws, and other failures are generic and leak no connection details", async () => {
            useDb({ createError: driverError("connect ECONNREFUSED mongodb://admin:hunter2@cluster0.example.net") });
            const result = await ensureVectorIndex();
            assert.equal(result.state, "unknown");
            assert.ok(!JSON.stringify(result.message).includes("hunter2"));
            assert.ok(!result.message.includes("cluster0"));
            assert.equal(result.index_created, false);
        });
    });

    describe("startup behaviour", () => {
        test("startup only submits the index and does not wait for the build", async () => {
            useDb();
            const logger = silentLogger();
            const { result, monitor } = await startVectorIndexSetup(process.env, {
                logger,
                pollIntervalMs: 80,
                maxPolls: 1,
            });
            assert.equal(result.state, "building");
            assert.ok(monitor, "a background monitor is started for a building index");
            const sentinel = Symbol("still running");
            assert.equal(await Promise.race([monitor, Promise.resolve(sentinel)]), sentinel, "monitor must not block startup");
            assert.ok(logger.lines.log.some((line) => /building; startup is not blocked/.test(line)));
            await monitor;
        });

        test("the monitor logs when a building index becomes ready", async () => {
            useDb();
            const logger = silentLogger();
            const { monitor } = await startVectorIndexSetup(process.env, { logger, pollIntervalMs: 5, maxPolls: 20 });
            setTimeout(() => {
                db.state.indexes[0].status = "READY";
                db.state.indexes[0].queryable = true;
            }, 15);
            const final = await monitor;
            assert.equal(final.state, "ready");
            assert.ok(logger.lines.log.some((line) => /is ready/.test(line)));
        });

        test("a ready index starts no monitor", async () => {
            useDb({ indexes: [readyIndex()] });
            const { result, monitor } = await startVectorIndexSetup(process.env, { logger: silentLogger() });
            assert.equal(result.state, "ready");
            assert.equal(monitor, null);
        });

        test("a permission error is logged clearly and startup continues", async () => {
            useDb({ createError: permissionError() });
            const logger = silentLogger();
            const { result, monitor } = await startVectorIndexSetup(process.env, { logger });
            assert.equal(result.state, "permission_denied");
            assert.equal(monitor, null);
            assert.ok(logger.lines.error.some((line) => /not permitted/.test(line)));
        });

        test("VECTOR_INDEX_AUTO_SETUP=false skips every database call", async () => {
            process.env.VECTOR_INDEX_AUTO_SETUP = "false";
            useDb({ collections: [] });
            const { result } = await startVectorIndexSetup(process.env, { logger: silentLogger() });
            assert.equal(result.state, "skipped");
            assert.equal(db.state.listCollectionCalls, 0);
            assert.equal(db.state.createdCollections.length, 0);
            assert.equal(db.state.createdIndexes.length, 0);
        });

        test("monitorVectorIndex gives up politely when the index never finishes", async () => {
            useDb({ indexes: [{ name: "vector_index", status: "BUILDING", queryable: false }] });
            const logger = silentLogger();
            const final = await monitorVectorIndex({ logger, intervalMs: 1, maxPolls: 3 });
            assert.equal(final.state, "building");
            assert.ok(logger.lines.warn.some((line) => /still building/.test(line)));
        });
    });

    describe("classification", () => {
        test("maps Atlas statuses to states", () => {
            assert.equal(classifyIndex({ status: "READY", queryable: true }, 384).state, "ready");
            assert.equal(classifyIndex({ status: "STALE", queryable: true }, 384).state, "ready");
            assert.equal(classifyIndex({ status: "PENDING", queryable: false }, 384).state, "building");
            assert.equal(classifyIndex({ status: "BUILDING" }, 384).state, "building");
            assert.equal(classifyIndex({ status: "FAILED" }, 384).state, "failed");
            assert.equal(classifyIndex({ status: "DOES_NOT_EXIST" }, 384).state, "missing");
            assert.equal(classifyIndex({}, 384).state, "ready", "deployments that report no status are treated as ready");
        });

        test("no tenant-specific logic anywhere in the setup code", () => {
            const sources = [
                path.resolve(__dirname, "../src/db/vectorIndex.js"),
                path.resolve(__dirname, "../../src/rag/vector_index.py"),
            ].map((file) => fs.readFileSync(file, "utf-8"));
            for (const tenant of PRESET_TENANTS) {
                for (const source of sources) {
                    assert.ok(!source.includes(tenant.tenant_id), `setup code must not name tenant '${tenant.tenant_id}'`);
                }
            }
            const calls = [];
            const spyDb = makeMockDb();
            const originalCollection = spyDb.collection;
            spyDb.collection = (name) => {
                calls.push(name);
                return originalCollection(name);
            };
            setDatabaseAdapter(spyDb);
            return ensureVectorIndex().then(() => {
                assert.deepEqual([...new Set(calls)], ["doc_vectors"], "only the shared vector collection is touched");
            });
        });
    });

    describe("GET /api/health", () => {
        let server;
        let baseUrl;

        beforeEach(async () => {
            process.env.OLLAMA_HOST = "http://127.0.0.1:1"; // refuse fast: Ollama is irrelevant here
            server = createApp().listen(0);
            await new Promise((resolve) => server.once("listening", resolve));
            baseUrl = `http://127.0.0.1:${server.address().port}`;
        });

        afterEach(async () => {
            server.closeAllConnections?.();
            await new Promise((resolve) => server.close(resolve));
        });

        const health = async () => {
            const response = await fetch(`${baseUrl}/api/health`);
            assert.equal(response.status, 200);
            return response.json();
        };

        test("missing -> vector_index_ready is false and the state says 'missing'", async () => {
            useDb();
            const body = await health();
            assert.equal(body.vector_index_ready, false);
            assert.equal(body.vector_index_state, "missing");
            assert.equal(body.vector_index.state, "missing");
            assert.equal(body.vector_index.name, "vector_index");
        });

        test("building -> not ready yet, state 'building'", async () => {
            useDb({ indexes: [{ name: "vector_index", status: "BUILDING", queryable: false }] });
            const body = await health();
            assert.equal(body.vector_index_ready, false);
            assert.equal(body.vector_index_state, "building");
        });

        test("ready -> vector_index_ready is true", async () => {
            useDb({ indexes: [readyIndex()] });
            const body = await health();
            assert.equal(body.vector_index_ready, true);
            assert.equal(body.vector_index_state, "ready");
            assert.equal(body.status, "ok");
        });

        test("vector_index_ready is always a boolean (client-training setup and the dashboard rely on it)", async () => {
            for (const options of [{}, { indexes: [readyIndex()] }, { listError: permissionError() }, { noSearchSupport: true }]) {
                useDb(options);
                assert.equal(typeof (await health()).vector_index_ready, "boolean");
            }
        });

        test("a permission problem is surfaced clearly, without leaking names or driver text", async () => {
            useDb({ listError: permissionError() });
            const body = await health();
            assert.equal(body.vector_index_ready, false);
            assert.equal(body.vector_index_state, "permission_denied");
            assert.match(body.vector_index.message, /database user is not permitted/i);
            assert.match(body.vector_index.message, /createSearchIndexes/);
            assert.equal(body.database_ready, true);
            const serialized = JSON.stringify(body).toLowerCase();
            assert.ok(!serialized.includes("mongodb"));
            assert.ok(!serialized.includes("example_db"));
            assert.ok(!serialized.includes("vector_setup_test_db"));
        });

        test("failed and misconfigured indexes are distinguished", async () => {
            useDb({ indexes: [{ name: "vector_index", status: "FAILED", queryable: false }] });
            assert.equal((await health()).vector_index_state, "failed");
            useDb({ indexes: [readyIndex({ latestDefinition: buildVectorIndexDefinition(768) })] });
            const body = await health();
            assert.equal(body.vector_index_state, "misconfigured");
            assert.equal(body.vector_index_ready, false);
        });

        test("an unreachable database reports 'unknown' and a degraded status", async () => {
            useDb({ countError: driverError("connection refused") });
            const body = await health();
            assert.equal(body.status, "degraded");
            assert.equal(body.database_ready, false);
            assert.equal(body.vector_index_ready, false);
            assert.equal(body.vector_index_state, "unknown");
        });

        test("a deployment without search support degrades to 'unknown'", async () => {
            useDb({ noSearchSupport: true });
            const body = await health();
            assert.equal(body.vector_index_state, "unknown");
            assert.equal(body.vector_index_ready, false);
        });

        test("reports whether automatic setup ran, and how the last attempt went", async () => {
            useDb();
            assert.deepEqual((await health()).vector_index.auto_setup, { enabled: true, attempted: false });
            await ensureVectorIndex();
            const body = await health();
            assert.equal(body.vector_index.auto_setup.attempted, true);
            assert.equal(body.vector_index.auto_setup.index_created, true);
            assert.ok(body.vector_index.auto_setup.attempted_at);
            process.env.VECTOR_INDEX_AUTO_SETUP = "false";
            assert.deepEqual((await health()).vector_index.auto_setup, { enabled: false });
        });

        test("the live status follows the build: missing, then building, then ready", async () => {
            useDb();
            assert.equal((await getVectorIndexStatus()).state, "missing");
            await ensureVectorIndex();
            assert.equal((await health()).vector_index_state, "building");
            db.state.indexes[0].status = "READY";
            db.state.indexes[0].queryable = true;
            const body = await health();
            assert.equal(body.vector_index_state, "ready");
            assert.equal(body.vector_index_ready, true);
        });
    });
});
