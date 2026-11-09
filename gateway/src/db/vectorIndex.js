/**
 * Automatic setup and live status of the Atlas Vector Search index on doc_vectors, so nobody has to
 * open the Atlas UI. Everything here is tenant-agnostic: one shared index, filtered by tenant_id at
 * query time (see AGENTS.md section 3). The definition mirrors src/rag/vector_index.py.
 *
 * - ensureVectorIndex()    creates missing collections and the index; idempotent, safe on every boot.
 *                          It only SUBMITS the index. Atlas builds it asynchronously and nothing here
 *                          waits for that, so startup is never blocked.
 * - getVectorIndexStatus() live state, used by /api/health.
 *
 * States: missing | building | ready | failed | misconfigured | permission_denied | unknown | skipped
 *
 * Messages returned from here end up in the public /api/health response, so they never contain
 * connection strings, database names or driver error text.
 */
const { getDb, getDocVectorsCollection } = require("./mongo");

const DEFAULT_INDEX_NAME = "vector_index";
const DEFAULT_DIMENSIONS = 384; // BAAI/bge-small-en-v1.5 and all-MiniLM-L6-v2 (AGENTS.md section 3)
const BASE_COLLECTIONS = ["businesses", "ticket_logs", "admin_users", "admin_sessions"];

function getVectorIndexName(env = process.env) {
    return String(env.MONGODB_VECTOR_INDEX_NAME || "").trim() || DEFAULT_INDEX_NAME;
}

function getDocVectorsCollectionName(env = process.env) {
    return String(env.MONGODB_COLLECTION_NAME || "").trim() || "doc_vectors";
}

function getExpectedDimensions(env = process.env) {
    const value = Number(env.VECTOR_INDEX_DIMENSIONS);
    return Number.isInteger(value) && value > 0 && value <= 4096 ? value : DEFAULT_DIMENSIONS;
}

function isAutoSetupEnabled(env = process.env) {
    const raw = String(env.VECTOR_INDEX_AUTO_SETUP ?? "true").trim().toLowerCase();
    return !["false", "0", "no", "off"].includes(raw);
}

function buildVectorIndexDefinition(numDimensions) {
    return {
        fields: [
            { type: "vector", path: "embedding", numDimensions, similarity: "cosine" },
            { type: "filter", path: "tenant_id" },
            { type: "filter", path: "doc_id" },
        ],
    };
}

function isPermissionError(error) {
    if (!error) return false;
    if (error.code === 13 || error.code === 8000 || error.codeName === "Unauthorized") return true;
    return /not authorized|unauthorized|not allowed to do action|requires authentication/i.test(
        String(error.message || "")
    );
}

function isNamespaceNotFound(error) {
    return Boolean(error) && (error.code === 26 || error.codeName === "NamespaceNotFound");
}

function isAlreadyExists(error) {
    if (!error) return false;
    if (error.code === 68 || error.codeName === "IndexAlreadyExists") return true;
    return /already exists|duplicate/i.test(String(error.message || ""));
}

function permissionMessage(collectionName, indexName) {
    return (
        `The database user is not permitted to create collections or to inspect/create Atlas Search ` +
        `indexes, so the vector index '${indexName}' on collection '${collectionName}' could not be set up. ` +
        "Grant the user Atlas search-index privileges (the createSearchIndexes and listSearchIndexes " +
        "actions, for example through a custom role or the built-in atlasAdmin role), or create the index " +
        "once by hand in Atlas using the shared definition. Set VECTOR_INDEX_AUTO_SETUP=false to stop the " +
        "automatic attempt."
    );
}

function indexedDimensions(index) {
    const definition = index.latestDefinition || index.definition || {};
    const field = (definition.fields || []).find((entry) => entry && entry.type === "vector");
    return field ? field.numDimensions : undefined;
}

/** Maps one listSearchIndexes entry to { state, message? }. */
function classifyIndex(index, expectedDimensions) {
    const status = String(index.status || index.state || "").toUpperCase();
    if (status === "DOES_NOT_EXIST") return { state: "missing" };

    const indexed = indexedDimensions(index);
    if (indexed !== undefined && expectedDimensions !== undefined && indexed !== expectedDimensions) {
        return {
            state: "misconfigured",
            message:
                `The index was built for ${indexed} dimensions but ${expectedDimensions} are expected. ` +
                "Drop and recreate the index (it is not changed automatically), or set VECTOR_INDEX_DIMENSIONS " +
                "to match the embedding model.",
        };
    }
    if (status === "FAILED") {
        return { state: "failed", message: "The server reports that the index build failed. Check the index in Atlas." };
    }
    if (index.queryable === true || status === "READY" || (status === "" && index.queryable === undefined)) {
        return { state: "ready" };
    }
    return { state: "building" };
}

/** Reads the index state from a collection. Throws driver errors other than "namespace not found". */
async function readIndexStatus(collection, env = process.env) {
    const name = getVectorIndexName(env);
    if (!collection || typeof collection.listSearchIndexes !== "function") {
        return {
            name,
            state: "unknown",
            message: "Search index inspection is not available on this database deployment.",
        };
    }
    let indexes;
    try {
        indexes = await collection.listSearchIndexes(name).toArray();
    } catch (error) {
        if (isNamespaceNotFound(error)) return { name, state: "missing" };
        throw error;
    }
    const match = indexes.find((index) => index && index.name === name);
    if (!match) return { name, state: "missing" };
    const { state, message } = classifyIndex(match, getExpectedDimensions(env));
    return { name, state, ...(message ? { message } : {}) };
}

/** Live status for /api/health. Never throws. */
async function getVectorIndexStatus(env = process.env) {
    const name = getVectorIndexName(env);
    try {
        return await readIndexStatus(await getDocVectorsCollection(), env);
    } catch (error) {
        if (isPermissionError(error)) {
            return { name, state: "permission_denied", message: permissionMessage(getDocVectorsCollectionName(env), name) };
        }
        return { name, state: "unknown", message: "The vector index state could not be read." };
    }
}

/** Creates the listed collections that do not exist yet. Returns { created, failures }. */
async function ensureCollections(db, names) {
    const existing = new Set((await db.listCollections({}, { nameOnly: true }).toArray()).map((entry) => entry.name));
    const created = [];
    const failures = [];
    for (const name of names) {
        if (existing.has(name)) continue;
        try {
            await db.createCollection(name);
            created.push(name);
        } catch (error) {
            if (error && (error.code === 48 || error.codeName === "NamespaceExists")) continue; // created concurrently
            failures.push({ collection: name, permission: isPermissionError(error) });
        }
    }
    return { created, failures };
}

let lastSetup = null;

function getLastVectorIndexSetup() {
    return lastSetup;
}

function resetVectorIndexState() {
    lastSetup = null;
}

/**
 * Ensures the required collections and the vector index exist. Idempotent: an existing index is
 * never recreated or modified. Returns the setup result and records it for /api/health. Never throws.
 */
async function ensureVectorIndex(env = process.env) {
    const name = getVectorIndexName(env);
    const collectionName = getDocVectorsCollectionName(env);
    const result = {
        name,
        state: "unknown",
        index_created: false,
        collections_created: [],
        attempted_at: new Date().toISOString(),
    };

    try {
        const db = await getDb();
        const names = [...new Set([...BASE_COLLECTIONS, collectionName])];
        const { created, failures } = await ensureCollections(db, names);
        result.collections_created = created;

        const vectorFailure = failures.find((failure) => failure.collection === collectionName);
        if (vectorFailure) {
            if (vectorFailure.permission) {
                result.state = "permission_denied";
                result.message = permissionMessage(collectionName, name);
            } else {
                result.message = "The vector collection could not be created.";
            }
        } else {
            const collection = db.collection(collectionName);
            const status = await readIndexStatus(collection, env);
            result.state = status.state;
            if (status.message) result.message = status.message;

            if (status.state === "missing") {
                try {
                    await collection.createSearchIndex({
                        name,
                        type: "vectorSearch",
                        definition: buildVectorIndexDefinition(getExpectedDimensions(env)),
                    });
                    result.index_created = true;
                } catch (error) {
                    if (!isAlreadyExists(error)) throw error; // another process created it first
                }
                result.state = "building";
                delete result.message;
            }
        }
    } catch (error) {
        if (isPermissionError(error)) {
            result.state = "permission_denied";
            result.message = permissionMessage(collectionName, name);
        } else {
            result.state = "unknown";
            result.message = "The vector index could not be set up.";
        }
        result.driver_error = error && error.name; // logged by the caller, never returned by /api/health
    }

    lastSetup = result;
    return result;
}

function sleep(ms) {
    return new Promise((resolve) => {
        const timer = setTimeout(resolve, ms);
        if (typeof timer.unref === "function") timer.unref();
    });
}

/** Polls (cheaply, in the background) until a building index stops building, then logs the outcome. */
async function monitorVectorIndex({ env = process.env, logger = console, intervalMs = 10000, maxPolls = 90 } = {}) {
    const name = getVectorIndexName(env);
    for (let poll = 0; poll < maxPolls; poll += 1) {
        await sleep(intervalMs);
        const status = await getVectorIndexStatus(env);
        if (status.state !== "building") {
            if (status.state === "ready") {
                logger.log(`[Gateway] Vector index '${name}' is ready.`);
            } else {
                logger.warn(`[Gateway] Vector index '${name}' is ${status.state}.${status.message ? ` ${status.message}` : ""}`);
            }
            return status;
        }
    }
    logger.warn(`[Gateway] Vector index '${name}' is still building; /api/health shows its current state.`);
    return { name, state: "building" };
}

/**
 * Startup hook. Awaiting it is quick (it only submits the index); the optional monitor keeps running
 * in the background and is never awaited by the server.
 */
async function startVectorIndexSetup(env = process.env, { logger = console, pollIntervalMs, maxPolls } = {}) {
    const name = getVectorIndexName(env);
    if (!isAutoSetupEnabled(env)) {
        lastSetup = { name, state: "skipped", index_created: false, collections_created: [], attempted_at: null };
        logger.log("[Gateway] Vector index auto-setup is disabled (VECTOR_INDEX_AUTO_SETUP=false).");
        return { result: lastSetup, monitor: null };
    }

    const result = await ensureVectorIndex(env);
    if (result.collections_created.length > 0) {
        logger.log(`[Gateway] Created collections: ${result.collections_created.join(", ")}`);
    }
    switch (result.state) {
        case "ready":
            logger.log(`[Gateway] Vector index '${name}' is ready.`);
            break;
        case "building":
            logger.log(
                `[Gateway] Vector index '${name}' ${result.index_created ? "was created and is" : "is"} building; ` +
                    "startup is not blocked. /api/health reports its state."
            );
            break;
        default:
            logger.error(`[Gateway] Vector index '${name}' is ${result.state}.${result.message ? ` ${result.message}` : ""}`);
            if (result.driver_error) logger.error(`[Gateway] Driver error type: ${result.driver_error}`);
    }

    const monitor =
        result.state === "building"
            ? monitorVectorIndex({
                  env,
                  logger,
                  intervalMs: pollIntervalMs ?? (Number(env.VECTOR_INDEX_POLL_MS) || 10000),
                  maxPolls: maxPolls ?? (Number(env.VECTOR_INDEX_POLL_MAX) || 90),
              }).catch(() => null)
            : null;
    return { result, monitor };
}

/** The part of the last setup attempt that is safe to show in /api/health. */
function summarizeSetupForHealth(env = process.env) {
    if (!isAutoSetupEnabled(env)) return { enabled: false };
    if (!lastSetup) return { enabled: true, attempted: false };
    return {
        enabled: true,
        attempted: lastSetup.state !== "skipped",
        attempted_at: lastSetup.attempted_at,
        index_created: lastSetup.index_created,
    };
}

module.exports = {
    DEFAULT_INDEX_NAME,
    DEFAULT_DIMENSIONS,
    buildVectorIndexDefinition,
    classifyIndex,
    ensureVectorIndex,
    getExpectedDimensions,
    getLastVectorIndexSetup,
    getVectorIndexName,
    getVectorIndexStatus,
    isAutoSetupEnabled,
    isPermissionError,
    monitorVectorIndex,
    permissionMessage,
    resetVectorIndexState,
    startVectorIndexSetup,
    summarizeSetupForHealth,
};
