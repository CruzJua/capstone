const express = require("express");
const cors = require("cors");
const { connectToDatabase } = require("./db/mongo");
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
    app.get("/api/health", (req, res) => {
        res.json({
            status: "ok",
            service: "orchestration-gateway",
            app_mode: getAppMode(process.env),
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
