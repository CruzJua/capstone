const path = require("path");
const { MongoClient } = require("mongodb");
const dotenv = require("dotenv");

// Load .env from project root regardless of working directory
const rootEnvPath = path.resolve(__dirname, "../../../.env");
dotenv.config({ path: rootEnvPath, override: true });
dotenv.config({ override: false });

const DEFAULT_TENANTS = [
    {
        tenant_id: "cinder_and_salt",
        name: "Cinder & Salt Bakery",
        industry: "Artisanal Bakery & Food Service",
        contact_email: "hello@cinderandsalt.com",
        team_name: "Bakery Guest Operations",
        agent_config: {
            system_prompt:
                "You are a customer support agent for Cinder & Salt Bakery. Answer customer questions about allergens, daily bake schedules, wholesale accounts, and catering strictly using the provided context chunks.",
            agent_tone: "Warm & Professional",
            temperature: 0.2,
            max_context_chunks: 4,
            similarity_threshold: 0.7,
        },
    },
    {
        tenant_id: "harbor_view",
        name: "Harbor View Veterinary Clinic",
        industry: "Veterinary Medicine & Pet Care",
        contact_email: "care@harborviewvet.com",
        team_name: "Client Care & Triage Team",
        agent_config: {
            system_prompt:
                "You are a customer support agent for Harbor View Veterinary Clinic. Provide accurate, grounded guidance on appointments, post-operative recovery, pharmacy refills, and emergency triage strictly using the provided context chunks.",
            agent_tone: "Empathetic & Clinical",
            temperature: 0.15,
            max_context_chunks: 4,
            similarity_threshold: 0.75,
        },
    },
    {
        tenant_id: "iron_and_oak",
        name: "Iron & Oak Provision Co.",
        industry: "Outdoor Apparel & Heritage Gear",
        contact_email: "support@ironandoak.com",
        team_name: "Outfitter Support Team",
        agent_config: {
            system_prompt:
                "You are a customer support agent for Iron & Oak Provision Co. Answer questions strictly using the provided context chunks.",
            agent_tone: "Rugged & Direct",
            temperature: 0.2,
            max_context_chunks: 4,
            similarity_threshold: 0.7,
        },
    },
    {
        tenant_id: "kettle_and_loom",
        name: "Kettle & Loom Cleaning Collective",
        industry: "Eco-Friendly Residential & Commercial Cleaning",
        contact_email: "concierge@kettleandloom.com",
        team_name: "Member Concierge Desk",
        agent_config: {
            system_prompt:
                "You are a customer support agent for Kettle & Loom Cleaning Collective. Answer client inquiries about chemical safety, property access, cancellations, and post-construction remediation strictly using the provided context chunks.",
            agent_tone: "Warm & Professional",
            temperature: 0.2,
            max_context_chunks: 4,
            similarity_threshold: 0.7,
        },
    },
    {
        tenant_id: "northstar_auto",
        name: "NorthStar Auto Care",
        industry: "Automotive Repair & Fleet Maintenance",
        contact_email: "service@northstarautocare.com",
        team_name: "Service Advisor Desk",
        agent_config: {
            system_prompt:
                "You are a customer support agent for NorthStar Auto Care. Answer questions regarding estimates, warranty coverage, fleet servicing, and seasonal maintenance strictly using the provided context chunks.",
            agent_tone: "Technical & Concise",
            temperature: 0.2,
            max_context_chunks: 4,
            similarity_threshold: 0.72,
        },
    },
];

let clientInstance = null;
let dbInstance = null;

async function ensureDefaultBusinesses(db) {
    const businesses = db.collection("businesses");
    await businesses.createIndex({ tenant_id: 1 }, { unique: true });

    const existingCount = await businesses.countDocuments();
    if (existingCount > 0) {
        return;
    }

    const nowIso = new Date().toISOString();
    for (const tenant of DEFAULT_TENANTS) {
        await businesses.updateOne(
            { tenant_id: tenant.tenant_id },
            {
                $setOnInsert: {
                    ...tenant,
                    updated_at: nowIso,
                },
            },
            { upsert: true }
        );
    }
}

async function connectToDatabase() {
    if (dbInstance && clientInstance) {
        return { client: clientInstance, db: dbInstance };
    }

    const mongoUri = process.env.MONGODB_URI;
    if (!mongoUri || mongoUri.includes("<username>") || mongoUri.includes("<password>")) {
        throw new Error(
            "MONGODB_URI is missing or contains placeholder values. Check your root .env file (see .env.example)."
        );
    }

    const dbName = process.env.MONGODB_DB_NAME || "capstone_dev";

    clientInstance = new MongoClient(mongoUri, {
        serverSelectionTimeoutMS: 8000,
        connectTimeoutMS: 8000,
    });

    await clientInstance.connect();
    dbInstance = clientInstance.db(dbName);

    await ensureDefaultBusinesses(dbInstance);

    return { client: clientInstance, db: dbInstance };
}

async function getDb() {
    if (!dbInstance) {
        await connectToDatabase();
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

async function closeDatabase() {
    if (clientInstance) {
        await clientInstance.close();
        clientInstance = null;
        dbInstance = null;
    }
}

module.exports = {
    connectToDatabase,
    getDb,
    getBusinessesCollection,
    getDocVectorsCollection,
    closeDatabase,
};

