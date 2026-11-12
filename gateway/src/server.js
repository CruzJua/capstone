// Load .env files before anything reads process.env (PORT, MONGODB_*, CHAT_*, WIDGET_*, ...).
const path = require("path");
const { loadEnv } = require("./config/env");
const loadedEnvFiles = loadEnv();

const express = require("express");
const cors = require("cors");
const {
    connectToDatabase,
    getBusinessesCollection,
} = require("./db/mongo");
const {
    getVectorIndexName,
    getVectorIndexStatus,
    startVectorIndexSetup,
    summarizeSetupForHealth,
} = require("./db/vectorIndex");
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
const { router: chatRouter } = require("./routes/chat");
const { router: widgetRouter } = require("./routes/widget");

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
    try {
        const businesses = await getBusinessesCollection();
        await businesses.countDocuments({}, { limit: 1 });
        databaseReady = true;
    } catch {
        // Keep boolean readiness flags false without exposing internal driver errors
    }

    const status = databaseReady
        ? await getVectorIndexStatus(env)
        : {
              name: getVectorIndexName(env),
              state: "unknown",
              message: "The database is not reachable.",
          };

    return {
        database_ready: databaseReady,
        // Stays a boolean (true only when the index is queryable): the compose healthcheck,
        // the client-training launcher and dashboard read it as one. The detailed state is
        // exposed separately as vector_index_state / vector_index.
        vector_index_ready: status.state === "ready",
        vector_index: {
            name: status.name,
            state: status.state,
            ...(status.message ? { message: status.message } : {}),
            auto_setup: summarizeSetupForHealth(env),
        },
    };
}

function createApp() {
    const app = express();
    app.set("json spaces", 4);

    // Behind a reverse proxy, set TRUST_PROXY (e.g. "1") so req.ip is the real client address for
    // rate limiting. Left unset, the socket address is used.
    const trustProxy = String(process.env.TRUST_PROXY || "").trim();
    if (trustProxy) {
        app.set("trust proxy", /^\d+$/.test(trustProxy) ? Number(trustProxy) : trustProxy);
    }

    // Public widget surface for third-party storefronts. These are mounted BEFORE the admin CORS
    // policy, CSRF origin check and requireAuth below: they are anonymous, send no credentials, and
    // apply their own origin allowlist and rate limits.
    app.use("/widget.js", widgetRouter);
    app.use("/api/chat", chatRouter);

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
            vector_index_state: dbStatus.vector_index.state,
            vector_index: dbStatus.vector_index,
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
        const repoRoot = path.resolve(__dirname, "../..");
        console.log(
            loadedEnvFiles.length > 0
                ? `[Gateway] Environment files loaded: ${loadedEnvFiles
                      .map((file) => path.relative(repoRoot, file))
                      .join(", ")}`
                : "[Gateway] No .env file found; using the process environment only"
        );
        await connectToDatabase(env);
        console.log(
            `[Gateway] Mode: ${runtimeConfig.appMode} | Connected to MongoDB Atlas`
        );

        const server = app.listen(PORT, () => {
            console.log(
                `[Gateway] Express Orchestration Gateway listening on http://localhost:${PORT}`
            );
        });

        // Ensure the vector collection and index exist. Deliberately not awaited: the gateway is
        // already serving, the index builds asynchronously, and /api/health reports its state.
        startVectorIndexSetup(env).catch((error) => {
            console.error(
                "[Gateway] Vector index setup failed unexpectedly:",
                error && error.name
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
