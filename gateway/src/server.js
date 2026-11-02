const express = require("express");
const cors = require("cors");
const { connectToDatabase } = require("./db/mongo");
const tenantsRouter = require("./routes/tenants");

const app = express();
const PORT = process.env.PORT || 4000;

app.use(
    cors({
        origin: ["http://localhost:3000", "http://127.0.0.1:3000"],
        methods: ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allowedHeaders: ["Content-Type", "Authorization"],
        credentials: true,
    })
);

app.use(express.json({ limit: "2mb" }));
app.set("json spaces", 4);

app.get("/api/health", (req, res) => {
    res.json({
        status: "ok",
        service: "orchestration-gateway",
        database: process.env.MONGODB_DB_NAME || "capstone_dev",
        timestamp: new Date().toISOString(),
    });
});

app.use("/api/tenants", tenantsRouter);

async function startServer() {
    try {
        const { db } = await connectToDatabase();
        console.log(`[Gateway] Connected to MongoDB Atlas database: ${db.databaseName}`);

        app.listen(PORT, () => {
            console.log(`[Gateway] Express Orchestration Gateway listening on http://localhost:${PORT}`);
        });
    } catch (error) {
        console.error("[Gateway] Failed to connect to MongoDB Atlas:", error.message);
        process.exit(1);
    }
}

if (require.main === module) {
    startServer();
}

module.exports = { app, startServer };

