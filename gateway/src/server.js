const express = require("express");
const cors = require("cors");
const {
    connectToDatabase,
    getBusinessesCollection,
    getDocVectorsCollection,
} = require("./db/mongo");
const { resolveRuntimeConfig, getAppMode } = require("./config/mode");
const {
    getAllowedOrigins,
    validateCsrfOrigin,
    requireAuth,
} = require("./middleware/auth");
const {
    publicAuthRouter,
    protectedAuthRouter,
} = require("./routes/auth");
const tenantsRouter = require("./routes/tenants");
const documentsRouter = require("./routes/documents");
const ticketsRouter = require("./routes/tickets");

async function checkOllamaReadiness(env = process.env) {
    const modelRequested = (env.OLLAMA_MODEL || "llama3.2:3b").trim();
    const ollamaHost = (
        env.OLLAMA_HOST || "http://127.0.0.1:11434"
    ).replace(/\/+$/, "");

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 1500);
    try {
        const res = await fetch(`${ollamaHost}/api/tags`, {
            method: "GET",
            signal: controller.signal,
        });
        if (!res.ok) {
            return {
                ollama_reachable: false,
                ollama_ready: false,
                model_requested: modelRequested,
            };
        }
        const payload = await res.json();
        const models = Array.isArray(payload?.models) ? payload.models : [];
        const candidates = modelRequested.includes(":")
            ? new Set([modelRequested])
            : new Set([modelRequested, `${modelRequested}:latest`]);
        const installed = models.some((m) =>
            candidates.has(String(m?.model || m?.name || ""))
        );
        return {
            ollama_reachable: true,
            ollama_ready: installed,
            model_requested: modelRequested,
        };
    } catch {
        return {
            ollama_reachable: false,
            ollama_ready: false,
            model_requested: modelRequested,
        };
    } finally {
        clearTimeout(timer);
    }
}

async function checkDatabaseAndVectorReadiness(env = process.env) {
    let databaseReady = false;
    let vectorIndexReady = false;
    const targetIndexName = (
        env.MONGODB_VECTOR_INDEX_NAME || "vector_index"
    ).trim();

    try {
        const businesses = await getBusinessesCollection();
        await businesses.countDocuments({}, { limit: 1 });
        databaseReady = true;

        const docVectors = await getDocVectorsCollection();
        if (typeof docVectors.listSearchIndexes === "function") {
            const indexes = await docVectors.listSearchIndexes().toArray();
            const matched = indexes.find(
                (idx) => idx && idx.name === targetIndexName
            );
            if (matched) {
                const status = String(
                    matched.status || matched.state || ""
                ).toUpperCase();
                vectorIndexReady =
                    status === "READY" ||
                    matched.queryable === true ||
                    status === "";
            }
        }
    } catch {
        // Keep boolean readiness flags false without exposing internal driver errors
    }

    return {
        database_ready: databaseReady,
        vector_index_ready: vectorIndexReady,
    };
}

function createApp() {
    const app = express();

    app.use(
        cors({
            origin: (origin, callback) => {
                if (!origin) {
                    return callback(null, true);
                }
                const allowed = getAllowedOrigins(process.env);
                if (allowed.has(origin)) {
                    return callback(null, true);
                }
                return callback(null, false);
            },
            methods: ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allowedHeaders: [
                "Content-Type",
                "Authorization",
                "X-Requested-With",
                "X-Tenant-Id",
            ],
            credentials: true,
        })
    );

    app.use(express.json({ limit: "2mb" }));
    app.set("json spaces", 4);

    // Validate Origin / CSRF on state-changing requests
    app.use("/api", validateCsrfOrigin);

    // Explicit Public Routes (Minimal Health + Public Auth Entrypoints)
    app.get("/api/health", async (req, res) => {
        const [dbStatus, ollamaStatus] = await Promise.all([
            checkDatabaseAndVectorReadiness(process.env),
            checkOllamaReadiness(process.env),
        ]);
        res.json({
            status: dbStatus.database_ready ? "ok" : "degraded",
            service: "orchestration-gateway",
            app_mode: getAppMode(process.env),
            database_ready: dbStatus.database_ready,
            vector_index_ready: dbStatus.vector_index_ready,
            ollama_reachable: ollamaStatus.ollama_reachable,
            ollama_ready: ollamaStatus.ollama_ready,
            model_requested: ollamaStatus.model_requested,
            timestamp: new Date().toISOString(),
        });
    });

    app.use("/api/auth", publicAuthRouter);

    // Authentication Boundary: All subsequent /api routes require a valid server-verified session
    app.use("/api", requireAuth);

    // Protected Routes
    app.use("/api/auth", protectedAuthRouter);
    app.use("/api/tenants", tenantsRouter);
    app.use("/api", documentsRouter);
    app.use("/api", ticketsRouter);

    return app;
}

const app = createApp();
const PORT = process.env.PORT || 4000;

async function startServer(env = process.env) {
    try {
        // Fail closed immediately on invalid APP_MODE or missing training DB config
        const runtimeConfig = resolveRuntimeConfig(env);
        await connectToDatabase(env);
        console.log(
            `[Gateway] Mode: ${runtimeConfig.appMode} | Connected to MongoDB Atlas`
        );

        const server = app.listen(PORT, () => {
            console.log(
                `[Gateway] Express Orchestration Gateway listening on http://localhost:${PORT}`
            );
        });

        const shutdown = () => {
            server.close(() => process.exit(0));
            setTimeout(() => process.exit(0), 500).unref();
        };
        process.on("SIGTERM", shutdown);
        process.on("SIGINT", shutdown);
        return server;
    } catch (error) {
        console.error(
            "[Gateway] Startup failed:",
            error.message
        );
        process.exit(1);
    }
}

if (require.main === module) {
    startServer();
}

module.exports = { app, createApp, startServer };
