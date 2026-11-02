const path = require("path");
const { MongoClient } = require("mongodb");
const dotenv = require("dotenv");
const { PRESET_TENANTS, SAMPLE_TICKETS } = require("../config/presets");
const { resolveRuntimeConfig } = require("../config/mode");

// Load .env from project root without clobbering explicit CLI environment variables
const rootEnvPath = path.resolve(__dirname, "../../../.env");
dotenv.config({ path: rootEnvPath, override: false });
dotenv.config({ override: false });

const DEFAULT_TENANTS = PRESET_TENANTS;
const DEFAULT_TICKETS = SAMPLE_TICKETS;

let clientInstance = null;
let dbInstance = null;
let connectedDbName = null;
let customDbAdapter = null;

async function ensureIndexes(db) {
    const businesses = db.collection("businesses");
    await businesses.createIndex({ tenant_id: 1 }, { unique: true });

    const ticketLogs = db.collection("ticket_logs");
    await ticketLogs.createIndex({ ticket_id: 1 }, { unique: true });
    await ticketLogs.createIndex({ tenant_id: 1, status: 1, created_at: -1 });

    const adminUsers = db.collection("admin_users");
    await adminUsers.createIndex({ email: 1 }, { unique: true });
    await adminUsers.createIndex({ user_id: 1 }, { unique: true });
    await adminUsers.createIndex({ tenant_id: 1 });

    const adminSessions = db.collection("admin_sessions");
    await adminSessions.createIndex({ session_id_hash: 1 }, { unique: true });
    await adminSessions.createIndex({ expires_at: 1 });
}

async function seedPresetTrainingData(db) {
    const businesses = db.collection("businesses");
    const ticketLogs = db.collection("ticket_logs");
    const nowIso = new Date().toISOString();

    for (const tenant of DEFAULT_TENANTS) {
        const { source_dir, source_documents, ...businessRecord } = tenant;
        await businesses.updateOne(
            { tenant_id: tenant.tenant_id },
            {
                $setOnInsert: {
                    ...businessRecord,
                    updated_at: nowIso,
                },
            },
            { upsert: true }
        );
    }

    for (const ticket of DEFAULT_TICKETS) {
        await ticketLogs.updateOne(
            { ticket_id: ticket.ticket_id },
            {
                $setOnInsert: {
                    ...ticket,
                    updated_at: nowIso,
                },
            },
            { upsert: true }
        );

        await ticketLogs.updateOne(
            {
                ticket_id: ticket.ticket_id,
                messages: { $exists: false },
            },
            {
                $set: {
                    customer_contact: ticket.customer_contact,
                    escalation_reason: ticket.escalation_reason,
                    ticket_summary: ticket.ticket_summary,
                    messages: ticket.messages,
                },
            }
        );
    }
}

async function initializeDatabaseForMode(db, appMode) {
    await ensureIndexes(db);
    if (appMode === "preset_training") {
        await seedPresetTrainingData(db);
    }
}

function setDatabaseAdapter(adapter) {
    customDbAdapter = adapter;
}

function resetDatabaseAdapter() {
    customDbAdapter = null;
}

async function connectToDatabase(env = process.env) {
    const runtimeConfig = resolveRuntimeConfig(env);
    const { appMode, activeDbName } = runtimeConfig;

    if (customDbAdapter) {
        const db =
            typeof customDbAdapter.getDbForName === "function"
                ? customDbAdapter.getDbForName(activeDbName)
                : customDbAdapter;
        await initializeDatabaseForMode(db, appMode);
        return { client: null, db, runtimeConfig };
    }

    if (dbInstance && clientInstance && connectedDbName === activeDbName) {
        return { client: clientInstance, db: dbInstance, runtimeConfig };
    }

    const mongoUri = env.MONGODB_URI;
    if (
        !mongoUri ||
        mongoUri.includes("<username>") ||
        mongoUri.includes("<password>")
    ) {
        throw new Error(
            "MONGODB_URI is missing or contains placeholder values. Check your root .env file (see .env.example)."
        );
    }

    if (!clientInstance) {
        clientInstance = new MongoClient(mongoUri, {
            serverSelectionTimeoutMS: 8000,
            connectTimeoutMS: 8000,
        });
        await clientInstance.connect();
    }

    dbInstance = clientInstance.db(activeDbName);
    connectedDbName = activeDbName;

    await initializeDatabaseForMode(dbInstance, appMode);

    return { client: clientInstance, db: dbInstance, runtimeConfig };
}

async function getDb() {
    const { activeDbName } = resolveRuntimeConfig(process.env);
    if (customDbAdapter) {
        return typeof customDbAdapter.getDbForName === "function"
            ? customDbAdapter.getDbForName(activeDbName)
            : customDbAdapter;
    }
    if (!dbInstance || connectedDbName !== activeDbName) {
        await connectToDatabase(process.env);
    }
    return dbInstance;
}

async function getBusinessesCollection() {
    const db = await getDb();
    return db.collection("businesses");
}

async function getDocVectorsCollection() {
    const db = await getDb();
    const collectionName = process.env.MONGODB_COLLECTION_NAME || "doc_vectors";
    return db.collection(collectionName);
}

async function getTicketLogsCollection() {
    const db = await getDb();
    return db.collection("ticket_logs");
}

async function getAdminUsersCollection() {
    const db = await getDb();
    return db.collection("admin_users");
}

async function getAdminSessionsCollection() {
    const db = await getDb();
    return db.collection("admin_sessions");
}

async function closeDatabase() {
    if (clientInstance) {
        await clientInstance.close();
        clientInstance = null;
        dbInstance = null;
        connectedDbName = null;
    }
}

module.exports = {
    DEFAULT_TENANTS,
    DEFAULT_TICKETS,
    connectToDatabase,
    initializeDatabaseForMode,
    getDb,
    getBusinessesCollection,
    getDocVectorsCollection,
    getTicketLogsCollection,
    getAdminUsersCollection,
    getAdminSessionsCollection,
    closeDatabase,
    setDatabaseAdapter,
    resetDatabaseAdapter,
};
