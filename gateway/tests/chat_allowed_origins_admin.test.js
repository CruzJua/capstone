const { test, describe, beforeEach, afterEach } = require("node:test");
const assert = require("node:assert/strict");
const { createApp } = require("../src/server");
const { setDatabaseAdapter, resetDatabaseAdapter } = require("../src/db/mongo");
const { setChatBackend } = require("../src/chat/backend");
const { resetChatState } = require("../src/routes/chat");
const { hashSessionToken } = require("../src/middleware/auth");

const RAW_TOKEN = "a".repeat(64);
const SESSION = "session-0123456789abcdef";

function setDotted(target, dottedKey, value) {
    const parts = dottedKey.split(".");
    let node = target;
    for (const part of parts.slice(0, -1)) {
        node[part] = node[part] && typeof node[part] === "object" ? node[part] : {};
        node = node[part];
    }
    node[parts[parts.length - 1]] = value;
}

describe("allowed origins are managed through the admin tenant config API", () => {
    let server;
    let baseUrl;
    let businesses;
    const savedEnv = { ...process.env };

    beforeEach(async () => {
        process.env.APP_MODE = "standard";
        process.env.MONGODB_DB_NAME = "origins_admin_db";
        delete process.env.MONGODB_TRAINING_DB_NAME;
        process.env.CHAT_RATE_LIMIT_PER_IP = "1000";
        process.env.CHAT_RATE_LIMIT_PER_SESSION = "1000";
        resetChatState();

        businesses = [
            { tenant_id: "tenant_a", name: "Tenant A", agent_config: {} },
            { tenant_id: "tenant_b", name: "Tenant B", agent_config: {} },
        ];
        const sessions = [
            {
                session_id_hash: hashSessionToken(RAW_TOKEN),
                user_id: "user_a",
                principal_type: "admin",
                tenant_id: "tenant_a",
                authorized_tenant_ids: ["tenant_a"],
                app_mode: "standard",
                expires_at: new Date(Date.now() + 3600 * 1000).toISOString(),
                revoked_at: null,
            },
        ];
        const adminUsers = [{ user_id: "user_a", principal_type: "admin", tenant_id: "tenant_a", email: "a@example.com" }];
        const match = (doc, query) => Object.entries(query).every(([key, value]) => doc[key] === value);

        setDatabaseAdapter({
            collection: (name) => {
                const store = { businesses, admin_sessions: sessions, admin_users: adminUsers }[name] || [];
                return {
                    findOne: async (query) => {
                        const found = store.find((doc) => match(doc, query));
                        return found ? structuredClone(found) : null;
                    },
                    findOneAndUpdate: async (query, update) => {
                        const found = store.find((doc) => match(doc, query));
                        if (!found) return null;
                        for (const [key, value] of Object.entries(update.$set || {})) setDotted(found, key, value);
                        return structuredClone(found);
                    },
                };
            },
        });
        setChatBackend({
            chat: () =>
                (async function* () {
                    yield { type: "sources", sources: [] };
                    yield { type: "token", text: "ok" };
                    yield { type: "done" };
                })(),
        });

        server = createApp().listen(0);
        await new Promise((resolve) => server.once("listening", resolve));
        baseUrl = `http://127.0.0.1:${server.address().port}`;
    });

    afterEach(async () => {
        server.closeAllConnections?.();
        await new Promise((resolve) => server.close(resolve));
        setChatBackend(null);
        resetDatabaseAdapter();
        for (const key of Object.keys(process.env)) {
            if (!(key in savedEnv)) delete process.env[key];
        }
        Object.assign(process.env, savedEnv);
    });

    const putConfig = (tenantId, body) =>
        fetch(`${baseUrl}/api/tenants/${tenantId}/config`, {
            method: "PUT",
            headers: {
                "Content-Type": "application/json",
                Cookie: `capstone_session=${RAW_TOKEN}`,
                Origin: "http://localhost:3000",
            },
            body: JSON.stringify(body),
        });

    const chatFrom = (origin, tenantId = "tenant_a") =>
        fetch(`${baseUrl}/api/chat`, {
            method: "POST",
            headers: { "Content-Type": "application/json", Accept: "application/json", Origin: origin },
            body: JSON.stringify({ tenant_id: tenantId, message: "hello", session_id: SESSION }),
        });

    test("an admin can set the list; the public endpoint then honours it immediately", async () => {
        const before = await chatFrom("https://shop.example.com");
        assert.equal(before.status, 403);
        await before.text();

        const updated = await putConfig("tenant_a", {
            widget_config: { allowed_origins: ["https://Shop.Example.com/", "https://shop.example.com"] },
        });
        assert.equal(updated.status, 200);
        assert.deepEqual((await updated.json()).widget_config.allowed_origins, ["https://shop.example.com"]);

        const after = await chatFrom("https://shop.example.com");
        assert.equal(after.status, 200);
        assert.equal((await after.json()).answer, "ok");
        const other = await chatFrom("https://evil.example.com");
        assert.equal(other.status, 403);
        await other.text();
    });

    test("wildcards, paths and non-origin values are rejected with 400 and nothing is stored", async () => {
        for (const allowed_origins of [["*"], ["https://*.example.com"], ["https://shop.example.com/cart"], "https://shop.example.com", [42]]) {
            const response = await putConfig("tenant_a", { widget_config: { allowed_origins } });
            assert.equal(response.status, 400, JSON.stringify(allowed_origins));
            await response.text();
        }
        assert.equal(businesses[0].widget_config, undefined);
    });

    test("an admin cannot change another tenant's allowed origins", async () => {
        const response = await putConfig("tenant_b", { widget_config: { allowed_origins: ["https://evil.example.com"] } });
        assert.ok([401, 403, 404].includes(response.status), `status was ${response.status}`);
        await response.text();
        assert.equal(businesses[1].widget_config, undefined);
    });

    test("the list is not writable without an admin session", async () => {
        const response = await fetch(`${baseUrl}/api/tenants/tenant_a/config`, {
            method: "PUT",
            headers: { "Content-Type": "application/json", Origin: "http://localhost:3000" },
            body: JSON.stringify({ widget_config: { allowed_origins: ["https://evil.example.com"] } }),
        });
        assert.equal(response.status, 401);
        await response.text();
        assert.equal(businesses[0].widget_config, undefined);
    });
});
