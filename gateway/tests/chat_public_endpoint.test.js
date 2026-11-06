const { test, describe, beforeEach, afterEach } = require("node:test");
const assert = require("node:assert/strict");
const { createApp } = require("../src/server");
const { setDatabaseAdapter, resetDatabaseAdapter } = require("../src/db/mongo");
const { setChatBackend } = require("../src/chat/backend");
const { ChatBackendError } = require("../src/chat/backend");
const { resetChatState } = require("../src/routes/chat");
const { PRESET_TENANTS } = require("../src/config/presets");

// A reserved preset (synthetic training) tenant id, taken from the repository's preset list.
const PRESET_ID = PRESET_TENANTS[0].tenant_id;
const DEFAULT_ORIGIN = "https://default.example.com";

const SESSION = "session-0123456789abcdef";
const OTHER_SESSION = "session-fedcba9876543210";

const TENANTS = [
    {
        tenant_id: "tenant_a",
        name: "Tenant A",
        agent_config: {
            system_prompt: "You are Tenant A support.",
            agent_tone: "warm",
            temperature: 0.35,
            max_context_chunks: 3,
            similarity_threshold: 0.75,
        },
        widget_config: { allowed_origins: ["https://shop.example.com"] },
    },
    {
        tenant_id: "tenant_b",
        name: "Tenant B",
        agent_config: { system_prompt: "Tenant B.", temperature: 0.1 },
        widget_config: { allowed_origins: ["https://other-shop.example.com"] },
    },
    // No widget_config: falls back to WIDGET_DEFAULT_ALLOWED_ORIGINS, which is unset (reject) by default.
    { tenant_id: "tenant_default", name: "Default Origins" },
    { tenant_id: "tenant_closed", name: "No Origins", widget_config: { allowed_origins: [] } },
    // Reserved preset (synthetic training) tenant.
    { tenant_id: PRESET_ID, name: "Preset tenant" },
];

function parseSse(text) {
    return text
        .split("\n\n")
        .filter((block) => block.trim() && !block.startsWith(":"))
        .map((block) => {
            const event = block.match(/^event: (.*)$/m)[1];
            const data = JSON.parse(block.match(/^data: (.*)$/m)[1]);
            return { event, data };
        });
}

function scriptedBackend(script) {
    const backend = {
        calls: [],
        aborted: false,
        closed: false,
        chat(payload, { signal }) {
            backend.calls.push({ payload, signal });
            signal.addEventListener("abort", () => {
                backend.aborted = true;
            });
            return (async function* () {
                try {
                    yield* script(payload, signal);
                } finally {
                    backend.closed = true;
                }
            })();
        },
    };
    return backend;
}

async function* happyScript() {
    // The extra `text` and `embedding` fields must never reach the visitor.
    yield {
        type: "sources",
        sources: [{ doc_id: "RETURNS", section: "Window", score: 0.83, text: "SECRET CHUNK", embedding: [0.1] }],
    };
    yield { type: "token", text: "Hello " };
    yield { type: "token", text: "world" };
    yield { type: "done", action: "answer" };
}

describe("POST /api/chat (public widget endpoint)", () => {
    let server;
    let baseUrl;
    let queries;
    const savedEnv = { ...process.env };

    beforeEach(async () => {
        process.env.APP_MODE = "standard";
        process.env.MONGODB_DB_NAME = "chat_test_db";
        delete process.env.MONGODB_TRAINING_DB_NAME;
        delete process.env.WIDGET_DEFAULT_ALLOWED_ORIGINS;
        process.env.CHAT_RATE_LIMIT_PER_IP = "1000";
        process.env.CHAT_RATE_LIMIT_PER_SESSION = "1000";
        process.env.CHAT_HEARTBEAT_MS = "60000";
        resetChatState();

        queries = [];
        setDatabaseAdapter({
            collection: (name) => ({
                findOne: async (query) => {
                    queries.push({ collection: name, query });
                    if (name !== "businesses" || typeof query.tenant_id !== "string") return null;
                    const found = TENANTS.find((tenant) => tenant.tenant_id === query.tenant_id);
                    return found ? structuredClone(found) : null;
                },
            }),
        });
        setChatBackend(scriptedBackend(happyScript));

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

    function post(body, { origin, accept = "text/event-stream", raw, contentType = "application/json", signal } = {}) {
        return fetch(`${baseUrl}/api/chat`, {
            method: "POST",
            headers: {
                "Content-Type": contentType,
                Accept: accept,
                ...(origin ? { Origin: origin } : {}),
            },
            body: raw !== undefined ? raw : JSON.stringify(body),
            signal,
        });
    }

    const valid = (overrides = {}) => ({
        tenant_id: "tenant_a",
        message: "What is your return policy?",
        session_id: SESSION,
        ...overrides,
    });

    async function assertError(response, status, code) {
        assert.equal(response.status, status);
        assert.match(response.headers.get("content-type"), /application\/json/);
        const body = await response.json();
        assert.deepEqual(Object.keys(body), ["error"]);
        assert.equal(body.error.code, code);
        assert.equal(typeof body.error.message, "string");
        return body;
    }

    describe("success", () => {
        test("streams only the model's tokens and done, with the required headers", async () => {
            const response = await post(valid(), { origin: "https://shop.example.com" });
            assert.equal(response.status, 200);
            assert.match(response.headers.get("content-type"), /^text\/event-stream/);
            assert.match(response.headers.get("cache-control"), /no-cache/);
            assert.match(response.headers.get("cache-control"), /no-transform/);
            assert.equal(response.headers.get("x-accel-buffering"), "no");
            assert.equal(response.headers.get("content-encoding"), null);
            assert.equal(response.headers.get("access-control-allow-origin"), "https://shop.example.com");
            assert.equal(response.headers.get("access-control-allow-credentials"), null);

            const events = parseSse(await response.text());
            assert.deepEqual(
                events.map((event) => event.event),
                ["token", "token", "done"]
            );
            assert.deepEqual(
                events.filter((event) => event.event === "token").map((event) => event.data.text),
                ["Hello ", "world"]
            );
            assert.deepEqual(events[2].data, {});
        });

        test("never sends document sources, chunk text, embeddings or the model's action to the visitor", async () => {
            const response = await post(valid());
            const text = await response.text();
            for (const leaked of ["sources", "RETURNS", "Window", "0.83", "SECRET CHUNK", "embedding", "action", "escalat", "confidence"]) {
                assert.ok(!text.includes(leaked), `visitor stream must not contain '${leaked}'`);
            }
        });

        test("falls back to one JSON body when the client does not accept SSE", async () => {
            const response = await post(valid(), { accept: "application/json" });
            assert.equal(response.status, 200);
            assert.match(response.headers.get("content-type"), /application\/json/);
            assert.deepEqual(await response.json(), { answer: "Hello world", session_id: SESSION });
        });

        test("JSON output is indented with four spaces", async () => {
            const response = await post(valid(), { accept: "application/json" });
            assert.match(await response.text(), /\n {4}"answer": "Hello world"/);
        });

        test("forwards the tenant's agent_config, normalized, to the backend", async () => {
            await (await post(valid())).text();
            const { payload } = setBackendCalls()[0];
            assert.equal(payload.tenant_id, "tenant_a");
            assert.equal(payload.query, "What is your return policy?");
            assert.deepEqual(payload.agent_config, {
                system_prompt: "You are Tenant A support.",
                agent_tone: "warm",
                temperature: 0.35,
                max_context_chunks: 3,
                similarity_threshold: 0.75,
            });
        });

        test("applies documented defaults when agent_config fields are missing", async () => {
            await (await post(valid({ tenant_id: "tenant_default" }))).text();
            assert.deepEqual(setBackendCalls()[0].payload.agent_config, {
                system_prompt: "",
                agent_tone: "",
                temperature: 0.2,
                max_context_chunks: 4,
                similarity_threshold: 0.7,
            });
        });

        test("keeps per-session history and sends it with the next message", async () => {
            await (await post(valid({ message: "First question" }))).text();
            await (await post(valid({ message: "Follow-up" }))).text();
            const calls = setBackendCalls();
            assert.deepEqual(calls[0].payload.history, []);
            assert.deepEqual(calls[1].payload.history, [
                { role: "user", content: "First question" },
                { role: "assistant", content: "Hello world" },
            ]);
        });

        test("requests without an Origin header are allowed (curl, server-side callers)", async () => {
            const response = await post(valid());
            assert.equal(response.status, 200);
            assert.equal(response.headers.get("access-control-allow-origin"), null);
            await response.text();
        });

        test("is reachable without any admin session or CSRF origin", async () => {
            // /api/tenants sits behind requireAuth; /api/chat must not.
            const admin = await fetch(`${baseUrl}/api/tenants`);
            assert.equal(admin.status, 401);
            const response = await post(valid(), { origin: "https://shop.example.com" });
            assert.equal(response.status, 200);
            await response.text();
        });
    });

    describe("validation errors", () => {
        test("400 invalid_request for missing or wrongly typed fields", async () => {
            const cases = [
                valid({ tenant_id: undefined }),
                valid({ tenant_id: "   " }),
                valid({ tenant_id: 42 }),
                valid({ message: undefined }),
                valid({ message: "   " }),
                valid({ message: { text: "hi" } }),
                valid({ session_id: undefined }),
                valid({ session_id: "short" }),
                valid({ session_id: "has spaces and ###### 1234567890" }),
                valid({ session_id: "x".repeat(129) }),
            ];
            for (const body of cases) {
                await assertError(await post(body), 400, "invalid_request");
            }
            assert.equal(setBackendCalls().length, 0);
        });

        test("400 invalid_request for non-object, malformed and non-JSON bodies", async () => {
            await assertError(await post(null, { raw: "[1,2]" }), 400, "invalid_request");
            await assertError(await post(null, { raw: "{not json" }), 400, "invalid_request");
            await assertError(await post(null, { raw: "hello", contentType: "text/plain" }), 400, "invalid_request");
        });

        test("400 invalid_request when the body exceeds the size cap", async () => {
            await assertError(await post(valid({ message: "x".repeat(40000) })), 400, "invalid_request");
        });

        test("400 message_too_long over 2000 characters; 2000 is accepted", async () => {
            await assertError(await post(valid({ message: "x".repeat(2001) })), 400, "message_too_long");
            const ok = await post(valid({ message: "x".repeat(2000) }));
            assert.equal(ok.status, 200);
            await ok.text();
        });

        test("405 for other methods and 404 for unknown sub-paths", async () => {
            const get = await fetch(`${baseUrl}/api/chat`);
            await assertError(get, 405, "method_not_allowed");
            assert.equal(get.headers.get("allow"), "POST, OPTIONS");
            await assertError(await fetch(`${baseUrl}/api/chat/other`, { method: "POST" }), 404, "not_found");
        });
    });

    describe("tenant scoping", () => {
        test("404 unknown_tenant for a tenant that does not exist", async () => {
            await assertError(await post(valid({ tenant_id: "tenant_missing" })), 404, "unknown_tenant");
            assert.equal(setBackendCalls().length, 0);
        });

        test("404 unknown_tenant for malformed ids without querying the database", async () => {
            for (const tenantId of ["../etc/passwd", "TENANT_A", "tenant a", "a", "x".repeat(80)]) {
                await assertError(await post(valid({ tenant_id: tenantId })), 404, "unknown_tenant");
            }
            assert.equal(queries.length, 0);
        });

        test("an object tenant_id (NoSQL operator injection) is rejected before any query", async () => {
            for (const tenantId of [{ $ne: null }, { $regex: ".*" }, ["tenant_a", "tenant_b"]]) {
                await assertError(await post(valid({ tenant_id: tenantId })), 400, "invalid_request");
            }
            assert.equal(queries.length, 0);
            assert.equal(setBackendCalls().length, 0);
        });

        test("the backend only ever receives the requested tenant", async () => {
            await (await post(valid({ tenant_id: "tenant_a" }))).text();
            await (
                await post(valid({ tenant_id: "tenant_b", session_id: OTHER_SESSION }), {
                    origin: "https://other-shop.example.com",
                })
            ).text();
            const tenants = setBackendCalls().map((call) => call.payload.tenant_id);
            assert.deepEqual(tenants, ["tenant_a", "tenant_b"]);
            assert.deepEqual(
                queries.map((entry) => entry.query),
                [{ tenant_id: "tenant_a" }, { tenant_id: "tenant_b" }]
            );
        });

        test("one tenant's session id can never read another tenant's history", async () => {
            await (await post(valid({ tenant_id: "tenant_a", message: "tenant A secret" }))).text();
            await (
                await post(valid({ tenant_id: "tenant_b", message: "hello from B" }), {
                    origin: "https://other-shop.example.com",
                })
            ).text();
            const second = setBackendCalls()[1].payload;
            assert.equal(second.tenant_id, "tenant_b");
            assert.deepEqual(second.history, []);
            assert.ok(!JSON.stringify(second).includes("tenant A secret"));
        });

        test("tenant A's agent_config is never used for tenant B", async () => {
            await (
                await post(valid({ tenant_id: "tenant_b" }), { origin: "https://other-shop.example.com" })
            ).text();
            const { agent_config: config } = setBackendCalls()[0].payload;
            assert.equal(config.system_prompt, "Tenant B.");
            assert.equal(config.temperature, 0.1);
        });

        test("standard mode hides reserved preset tenants", async () => {
            await assertError(await post(valid({ tenant_id: PRESET_ID })), 404, "unknown_tenant");
        });

        test("preset_training mode serves only preset tenants", async () => {
            process.env.APP_MODE = "preset_training";
            process.env.MONGODB_TRAINING_DB_NAME = "chat_training_db";
            const hidden = await post(valid({ tenant_id: "tenant_a" }));
            await assertError(hidden, 404, "unknown_tenant");
            const served = await post(valid({ tenant_id: PRESET_ID }));
            assert.equal(served.status, 200);
            await served.text();
        });
    });

    describe("CORS and origin allowlist", () => {
        test("preflight allows POST with Content-Type only and never credentials", async () => {
            const response = await fetch(`${baseUrl}/api/chat`, {
                method: "OPTIONS",
                headers: {
                    Origin: "https://shop.example.com",
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "content-type",
                },
            });
            assert.equal(response.status, 204);
            assert.equal(response.headers.get("access-control-allow-origin"), "https://shop.example.com");
            assert.equal(response.headers.get("access-control-allow-methods"), "POST, OPTIONS");
            assert.equal(response.headers.get("access-control-allow-headers"), "Content-Type");
            assert.equal(response.headers.get("access-control-allow-credentials"), null);
            assert.match(response.headers.get("vary"), /Origin/);
        });

        test("preflight does not touch the database or the backend", async () => {
            await fetch(`${baseUrl}/api/chat`, { method: "OPTIONS", headers: { Origin: "https://x.example" } });
            assert.equal(queries.length, 0);
            assert.equal(setBackendCalls().length, 0);
        });

        test("403 origin_not_allowed for an origin outside the tenant's list, before the backend runs", async () => {
            const response = await post(valid(), { origin: "https://evil.example.com" });
            await assertError(response, 403, "origin_not_allowed");
            // Echoed so the widget can read the error body; still no credentials.
            assert.equal(response.headers.get("access-control-allow-origin"), "https://evil.example.com");
            assert.equal(response.headers.get("access-control-allow-credentials"), null);
            assert.equal(setBackendCalls().length, 0);
        });

        test("origin lists are per tenant", async () => {
            const crossOrigin = await post(valid({ tenant_id: "tenant_b" }), { origin: "https://shop.example.com" });
            await assertError(crossOrigin, 403, "origin_not_allowed");
            const own = await post(valid({ tenant_id: "tenant_b" }), { origin: "https://other-shop.example.com" });
            assert.equal(own.status, 200);
            await own.text();
        });

        test("origin matching is exact (scheme, host and port)", async () => {
            for (const origin of [
                "http://shop.example.com",
                "https://shop.example.com:8443",
                "https://shop.example.com.evil.com",
                "https://sub.shop.example.com",
                "null",
            ]) {
                await assertError(await post(valid(), { origin }), 403, "origin_not_allowed");
            }
        });

        test("a tenant without its own list rejects every origin when WIDGET_DEFAULT_ALLOWED_ORIGINS is unset", async () => {
            assert.equal(process.env.WIDGET_DEFAULT_ALLOWED_ORIGINS, undefined);
            for (const origin of [DEFAULT_ORIGIN, "https://shop.example.com", "http://dev.example.com"]) {
                await assertError(
                    await post(valid({ tenant_id: "tenant_default" }), { origin }),
                    403,
                    "origin_not_allowed"
                );
            }
            process.env.WIDGET_DEFAULT_ALLOWED_ORIGINS = "";
            await assertError(
                await post(valid({ tenant_id: "tenant_default" }), { origin: DEFAULT_ORIGIN }),
                403,
                "origin_not_allowed"
            );
            assert.equal(setBackendCalls().length, 0);
        });

        test("a tenant without its own list uses WIDGET_DEFAULT_ALLOWED_ORIGINS when it is set", async () => {
            process.env.WIDGET_DEFAULT_ALLOWED_ORIGINS = `${DEFAULT_ORIGIN}, https://staging.example.com`;
            const allowed = await post(valid({ tenant_id: "tenant_default" }), { origin: DEFAULT_ORIGIN });
            assert.equal(allowed.status, 200);
            await allowed.text();
            await assertError(
                await post(valid({ tenant_id: "tenant_default" }), { origin: "https://evil.example.com" }),
                403,
                "origin_not_allowed"
            );
        });

        test("a tenant's own list always wins over the env default", async () => {
            process.env.WIDGET_DEFAULT_ALLOWED_ORIGINS = DEFAULT_ORIGIN;
            await assertError(
                await post(valid({ tenant_id: "tenant_b" }), { origin: DEFAULT_ORIGIN }),
                403,
                "origin_not_allowed"
            );
        });

        test("an explicitly empty list allows no browser origin, even with an env default", async () => {
            process.env.WIDGET_DEFAULT_ALLOWED_ORIGINS = DEFAULT_ORIGIN;
            await assertError(
                await post(valid({ tenant_id: "tenant_closed" }), { origin: DEFAULT_ORIGIN }),
                403,
                "origin_not_allowed"
            );
        });

        test("admin CORS policy for the dashboard is unchanged", async () => {
            const response = await fetch(`${baseUrl}/api/tenants`, {
                method: "OPTIONS",
                headers: { Origin: "http://localhost:3000", "Access-Control-Request-Method": "GET" },
            });
            assert.equal(response.headers.get("access-control-allow-origin"), "http://localhost:3000");
            assert.equal(response.headers.get("access-control-allow-credentials"), "true");
        });
    });

    describe("rate limiting", () => {
        test("429 rate_limited per session, with Retry-After", async () => {
            process.env.CHAT_RATE_LIMIT_PER_SESSION = "2";
            for (let i = 0; i < 2; i += 1) {
                const ok = await post(valid());
                assert.equal(ok.status, 200);
                await ok.text();
            }
            const limited = await post(valid());
            await assertError(limited, 429, "rate_limited");
            assert.ok(Number(limited.headers.get("retry-after")) >= 1);
            const other = await post(valid({ session_id: OTHER_SESSION }));
            assert.equal(other.status, 200);
            await other.text();
        });

        test("429 rate_limited per IP across sessions", async () => {
            process.env.CHAT_RATE_LIMIT_PER_IP = "2";
            for (const session of [SESSION, OTHER_SESSION]) {
                const ok = await post(valid({ session_id: session }));
                assert.equal(ok.status, 200);
                await ok.text();
            }
            const limited = await post(valid({ session_id: "session-third-0123456789" }));
            await assertError(limited, 429, "rate_limited");
            assert.ok(Number(limited.headers.get("retry-after")) >= 1);
        });

        test("rate limited requests never reach the database or backend", async () => {
            process.env.CHAT_RATE_LIMIT_PER_IP = "1";
            await (await post(valid())).text();
            const before = { queries: queries.length, calls: setBackendCalls().length };
            await assertError(await post(valid()), 429, "rate_limited");
            assert.equal(queries.length, before.queries);
            assert.equal(setBackendCalls().length, before.calls);
        });

        test("the window slides: allowed again after it passes", async () => {
            process.env.CHAT_RATE_LIMIT_PER_SESSION = "1";
            process.env.CHAT_RATE_LIMIT_WINDOW_MS = "150";
            await (await post(valid())).text();
            await assertError(await post(valid()), 429, "rate_limited");
            await new Promise((resolve) => setTimeout(resolve, 200));
            const again = await post(valid());
            assert.equal(again.status, 200);
            await again.text();
        });
    });

    describe("backend failures", () => {
        test("503 service_unavailable when the backend is unreachable", async () => {
            setChatBackend({
                chat: () => {
                    throw new ChatBackendError("connect ECONNREFUSED 10.0.0.5:8100");
                },
            });
            const body = await assertError(await post(valid()), 503, "service_unavailable");
            assert.ok(!JSON.stringify(body).includes("10.0.0.5"));
        });

        test("503 service_unavailable when the backend fails before its first event", async () => {
            setChatBackend(
                scriptedBackend(async function* () {
                    throw new ChatBackendError("status 500");
                })
            );
            await assertError(await post(valid()), 503, "service_unavailable");
        });

        test("503 service_unavailable when retrieval fails (first event is an error)", async () => {
            setChatBackend(
                scriptedBackend(async function* () {
                    yield { type: "error", code: "retrieval_failed", message: "mongodb://user:pw@host" };
                })
            );
            const body = await assertError(await post(valid()), 503, "service_unavailable");
            assert.ok(!JSON.stringify(body).includes("mongodb://"));
        });

        test("503 service_unavailable when the tenant lookup fails", async () => {
            setDatabaseAdapter({
                collection: () => ({
                    findOne: async () => {
                        throw new Error("Atlas unreachable: secret-host");
                    },
                }),
            });
            const body = await assertError(await post(valid()), 503, "service_unavailable");
            assert.ok(!JSON.stringify(body).includes("secret-host"));
        });

        test("a failure after streaming starts becomes an error event with no done", async () => {
            setChatBackend(
                scriptedBackend(async function* () {
                    yield { type: "sources", sources: [] };
                    yield { type: "token", text: "Par" };
                    yield { type: "error", code: "generation_failed", message: "Traceback ..." };
                })
            );
            const response = await post(valid());
            assert.equal(response.status, 200);
            const events = parseSse(await response.text());
            assert.deepEqual(
                events.map((event) => event.event),
                ["token", "error"]
            );
            assert.equal(events[1].data.code, "generation_failed");
            assert.ok(!JSON.stringify(events[1].data).includes("Traceback"));
        });

        test("a backend that throws mid-stream becomes an error event", async () => {
            setChatBackend(
                scriptedBackend(async function* () {
                    yield { type: "sources", sources: [] };
                    yield { type: "token", text: "Par" };
                    throw new Error("socket hang up");
                })
            );
            const events = parseSse(await (await post(valid())).text());
            assert.equal(events[events.length - 1].event, "error");
            assert.ok(!events.some((event) => event.event === "done"));
        });

        test("a backend that ends without done becomes an error event", async () => {
            setChatBackend(
                scriptedBackend(async function* () {
                    yield { type: "sources", sources: [] };
                    yield { type: "token", text: "Par" };
                })
            );
            const events = parseSse(await (await post(valid())).text());
            assert.equal(events[events.length - 1].event, "error");
        });

        test("failed replies are not remembered in the session history", async () => {
            setChatBackend(
                scriptedBackend(async function* () {
                    yield { type: "sources", sources: [] };
                    yield { type: "token", text: "Par" };
                    yield { type: "error", code: "generation_failed", message: "x" };
                })
            );
            await (await post(valid({ message: "will fail" }))).text();
            const backend = scriptedBackend(happyScript);
            setChatBackend(backend);
            await (await post(valid({ message: "retry" }))).text();
            assert.deepEqual(backend.calls[0].payload.history, []);
        });

        test("the overall duration limit ends a stalled generation with a timeout error", async () => {
            process.env.CHAT_MAX_DURATION_MS = "150";
            setChatBackend(
                scriptedBackend(async function* (payload, signal) {
                    yield { type: "sources", sources: [] };
                    await new Promise((resolve) => signal.addEventListener("abort", resolve));
                })
            );
            const events = parseSse(await (await post(valid())).text());
            assert.equal(events[events.length - 1].event, "error");
            assert.equal(events[events.length - 1].data.code, "timeout");
        });

        test("heartbeat comments keep a slow stream alive", async () => {
            process.env.CHAT_HEARTBEAT_MS = "40";
            setChatBackend(
                scriptedBackend(async function* () {
                    yield { type: "sources", sources: [] };
                    await new Promise((resolve) => setTimeout(resolve, 200));
                    yield { type: "token", text: "late" };
                    yield { type: "done" };
                })
            );
            const text = await (await post(valid())).text();
            assert.ok(text.includes(": ping"));
            assert.deepEqual(
                parseSse(text).map((event) => event.event),
                ["token", "done"]
            );
        });
    });

    describe("client disconnect", () => {
        async function waitFor(predicate, timeoutMs = 2000) {
            const started = Date.now();
            while (!predicate()) {
                if (Date.now() - started > timeoutMs) return false;
                await new Promise((resolve) => setTimeout(resolve, 10));
            }
            return true;
        }

        test("aborts generation and closes the backend stream when the visitor disconnects", async () => {
            const backend = scriptedBackend(async function* (payload, signal) {
                yield { type: "sources", sources: [] };
                yield { type: "token", text: "Hello " };
                await new Promise((resolve) => signal.addEventListener("abort", resolve));
            });
            setChatBackend(backend);

            const controller = new AbortController();
            const response = await post(valid(), { signal: controller.signal });
            const reader = response.body.getReader();
            await reader.read(); // at least one event has arrived
            assert.equal(backend.aborted, false);
            controller.abort();
            await reader.cancel().catch(() => {});

            assert.ok(await waitFor(() => backend.aborted), "backend signal should be aborted");
            assert.ok(await waitFor(() => backend.closed), "backend stream should be closed");
        });

        test("aborts a pending JSON-mode request when the visitor disconnects", async () => {
            const backend = scriptedBackend(async function* (payload, signal) {
                yield { type: "sources", sources: [] };
                await new Promise((resolve) => signal.addEventListener("abort", resolve));
            });
            setChatBackend(backend);
            const controller = new AbortController();
            const pending = post(valid(), { accept: "application/json", signal: controller.signal }).catch(() => null);
            assert.ok(await waitFor(() => backend.calls.length === 1));
            controller.abort();
            await pending;
            assert.ok(await waitFor(() => backend.aborted), "backend signal should be aborted");
        });

        test("a completed reply does not abort the backend", async () => {
            const backend = scriptedBackend(happyScript);
            setChatBackend(backend);
            await (await post(valid())).text();
            await new Promise((resolve) => setTimeout(resolve, 50));
            assert.equal(backend.aborted, false);
            assert.equal(backend.closed, true);
        });
    });

    function setBackendCalls() {
        // The active backend is whichever the test installed last; read its recorded calls.
        const { getChatBackend } = require("../src/chat/backend");
        return getChatBackend(process.env).calls || [];
    }
});
