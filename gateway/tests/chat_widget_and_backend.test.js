const { test, describe, beforeEach, afterEach } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
const { createApp } = require("../src/server");
const { setDatabaseAdapter, resetDatabaseAdapter } = require("../src/db/mongo");
const { setChatBackend, createHttpChatBackend, ChatBackendError } = require("../src/chat/backend");
const { resetChatState, buildAgentConfig } = require("../src/routes/chat");
const { getWidgetPath } = require("../src/routes/widget");
const { SlidingWindowLimiter } = require("../src/middleware/rateLimit");
const { SessionHistory } = require("../src/chat/sessionHistory");
const { getChatConfig } = require("../src/chat/config");
const {
    parseOriginStrict,
    parseAllowedOrigins,
    resolveAllowedOrigins,
    isOriginAllowed,
} = require("../src/chat/origins");

const SESSION = "session-0123456789abcdef";

function listen(server) {
    return new Promise((resolve) => server.listen(0, "127.0.0.1", () => resolve(server.address().port)));
}

function close(server) {
    server.closeAllConnections?.();
    return new Promise((resolve) => server.close(resolve));
}

async function collect(iterable) {
    const events = [];
    for await (const event of iterable) events.push(event);
    return events;
}

describe("GET /widget.js", () => {
    let server;
    let baseUrl;
    let tmpDir;
    const savedEnv = { ...process.env };

    beforeEach(async () => {
        tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "widget-route-"));
        fs.writeFileSync(path.join(tmpDir, "widget.js"), "(function(){window.__widget=1})();\n");
        process.env.WIDGET_DIST_PATH = path.join(tmpDir, "widget.js");
        server = createApp().listen(0);
        await new Promise((resolve) => server.once("listening", resolve));
        baseUrl = `http://127.0.0.1:${server.address().port}`;
    });

    afterEach(async () => {
        await close(server);
        fs.rmSync(tmpDir, { recursive: true, force: true });
        for (const key of Object.keys(process.env)) {
            if (!(key in savedEnv)) delete process.env[key];
        }
        Object.assign(process.env, savedEnv);
    });

    test("serves the built bundle as JavaScript without credentials or CSP", async () => {
        const response = await fetch(`${baseUrl}/widget.js`);
        assert.equal(response.status, 200);
        assert.match(response.headers.get("content-type"), /^text\/javascript/);
        assert.equal(await response.text(), "(function(){window.__widget=1})();\n");
        assert.equal(response.headers.get("set-cookie"), null);
        assert.equal(response.headers.get("access-control-allow-credentials"), null);
        assert.equal(response.headers.get("access-control-allow-origin"), "*");
        assert.equal(response.headers.get("content-security-policy"), null);
        assert.equal(response.headers.get("x-content-type-options"), "nosniff");
        assert.equal(response.headers.get("cross-origin-resource-policy"), "cross-origin");
        assert.match(response.headers.get("cache-control"), /no-cache/);
    });

    test("needs no admin session", async () => {
        const response = await fetch(`${baseUrl}/widget.js`, { headers: { Origin: "https://anywhere.example" } });
        assert.equal(response.status, 200);
        await response.text();
    });

    test("answers conditional requests with 304", async () => {
        const first = await fetch(`${baseUrl}/widget.js`);
        const etag = first.headers.get("etag");
        assert.ok(etag);
        await first.text();
        // Raw http: fetch() adds "Cache-Control: no-cache" whenever If-None-Match is set, which
        // (correctly) forces a full response and would hide what browsers' script loads do.
        const status = await new Promise((resolve, reject) => {
            http.get(`${baseUrl}/widget.js`, { headers: { "If-None-Match": etag } }, (res) => {
                res.resume();
                res.on("end", () => resolve(res.statusCode));
            }).on("error", reject);
        });
        assert.equal(status, 304);
    });

    test("serves a rebuilt bundle without restarting the gateway", async () => {
        await (await fetch(`${baseUrl}/widget.js`)).text();
        fs.writeFileSync(process.env.WIDGET_DIST_PATH, "window.__widget=2;\n");
        const response = await fetch(`${baseUrl}/widget.js`);
        assert.equal(await response.text(), "window.__widget=2;\n");
    });

    test("404 widget_not_built with a JSON error when the bundle is missing", async () => {
        process.env.WIDGET_DIST_PATH = path.join(tmpDir, "missing.js");
        const response = await fetch(`${baseUrl}/widget.js`);
        assert.equal(response.status, 404);
        assert.match(response.headers.get("content-type"), /application\/json/);
        const body = await response.json();
        assert.equal(body.error.code, "widget_not_built");
        assert.match(body.error.message, /npm run build:embed/);
    });

    test("only GET and HEAD are allowed", async () => {
        const response = await fetch(`${baseUrl}/widget.js`, { method: "POST" });
        assert.equal(response.status, 405);
        assert.equal(response.headers.get("allow"), "GET, HEAD");
        await response.text();
    });

    test("defaults to widget/dist/widget.js in the repository", () => {
        delete process.env.WIDGET_DIST_PATH;
        assert.ok(getWidgetPath(process.env).endsWith(path.join("widget", "dist", "widget.js")));
    });
});

describe("HTTP chat backend client", () => {
    let stub;
    let stubUrl;
    let received;

    function startStub(handler) {
        stub = http.createServer((req, res) => {
            let body = "";
            req.on("data", (chunk) => {
                body += chunk;
            });
            req.on("end", () => {
                received.push({ method: req.method, url: req.url, headers: req.headers, body: body && JSON.parse(body) });
                handler(req, res);
            });
        });
        return listen(stub).then((port) => {
            stubUrl = `http://127.0.0.1:${port}`;
        });
    }

    beforeEach(() => {
        received = [];
    });

    afterEach(async () => {
        if (stub) await close(stub);
        stub = null;
    });

    test("parses newline-delimited events split across arbitrary chunk boundaries", async () => {
        const wire =
            '{"type":"sources","sources":[{"doc_id":"A","section":"S","score":0.9}]}\n' +
            '{"type":"token","text":"Hel"}\n{"type":"token","text":"lo"}\n{"type":"done","action":"answer"}\n';
        await startStub((req, res) => {
            res.writeHead(200, { "Content-Type": "application/x-ndjson" });
            for (let i = 0; i < wire.length; i += 7) res.write(wire.slice(i, i + 7));
            res.end();
        });
        const backend = createHttpChatBackend({ url: stubUrl, token: "s3cret" });
        const events = await collect(backend.chat({ tenant_id: "t", query: "q" }, {}));
        assert.deepEqual(
            events.map((event) => event.type),
            ["sources", "token", "token", "done"]
        );
        assert.equal(received[0].url, "/v1/chat");
        assert.equal(received[0].method, "POST");
        assert.equal(received[0].headers["x-chat-backend-token"], "s3cret");
        assert.deepEqual(received[0].body, { tenant_id: "t", query: "q" });
    });

    test("sends no token header when none is configured", async () => {
        await startStub((req, res) => {
            res.writeHead(200);
            res.end('{"type":"done"}\n');
        });
        await collect(createHttpChatBackend({ url: stubUrl }).chat({}, {}));
        assert.equal(received[0].headers["x-chat-backend-token"], undefined);
    });

    test("handles a final event without a trailing newline", async () => {
        await startStub((req, res) => {
            res.writeHead(200);
            res.end('{"type":"token","text":"a"}\n{"type":"done"}');
        });
        const events = await collect(createHttpChatBackend({ url: stubUrl }).chat({}, {}));
        assert.equal(events[events.length - 1].type, "done");
    });

    test("throws ChatBackendError for non-200 responses, malformed events and unreachable hosts", async () => {
        await startStub((req, res) => {
            res.writeHead(500);
            res.end("boom");
        });
        await assert.rejects(collect(createHttpChatBackend({ url: stubUrl }).chat({}, {})), ChatBackendError);
        await close(stub);

        await startStub((req, res) => {
            res.writeHead(200);
            res.end("not json\n");
        });
        await assert.rejects(collect(createHttpChatBackend({ url: stubUrl }).chat({}, {})), ChatBackendError);
        await close(stub);
        stub = null;

        await assert.rejects(
            collect(createHttpChatBackend({ url: "http://127.0.0.1:1" }).chat({}, {})),
            (error) => error instanceof ChatBackendError && !error.message.includes("127.0.0.1")
        );
    });

    test("aborting the signal closes the upstream connection", async () => {
        let upstreamClosed = false;
        await startStub((req, res) => {
            res.writeHead(200);
            res.write('{"type":"sources","sources":[]}\n');
            res.on("close", () => {
                upstreamClosed = true;
            });
        });
        const controller = new AbortController();
        const iterator = createHttpChatBackend({ url: stubUrl })
            .chat({}, { signal: controller.signal })
            [Symbol.asyncIterator]();
        assert.equal((await iterator.next()).value.type, "sources");
        controller.abort();
        await assert.rejects(iterator.next());
        for (let i = 0; i < 100 && !upstreamClosed; i += 1) await new Promise((r) => setTimeout(r, 10));
        assert.ok(upstreamClosed);
    });
});

describe("gateway end to end through the HTTP chat backend (stub service)", () => {
    let gateway;
    let gatewayUrl;
    let stub;
    let stubRequests;
    let upstreamClosed;
    let escalationWrites;
    const savedEnv = { ...process.env };

    beforeEach(async () => {
        stubRequests = [];
        upstreamClosed = false;
        stub = http.createServer((req, res) => {
            let body = "";
            req.on("data", (chunk) => {
                body += chunk;
            });
            req.on("end", () => {
                const payload = JSON.parse(body);
                stubRequests.push({ headers: req.headers, payload });
                res.writeHead(200, { "Content-Type": "application/x-ndjson" });
                res.write('{"type":"sources","sources":[{"doc_id":"RETURNS","section":"Window","score":0.9,"text":"LEAK"}]}\n');
                if (payload.query.includes("hang")) {
                    res.on("close", () => {
                        upstreamClosed = true;
                    });
                    return;
                }
                res.write('{"type":"token","text":"Thirty "}\n{"type":"token","text":"days."}\n');
                // Same wire format the Python chat service sends (src/chat/server.py).
                res.end(
                    payload.query.includes("refund")
                        ? '{"type":"done","action":"escalate","confidence":0.4,"cited_sources":[]}\n'
                        : '{"type":"done","action":"answer","confidence":0.9,"cited_sources":["RETURNS"]}\n'
                );
            });
        });
        const stubPort = await listen(stub);

        process.env.APP_MODE = "standard";
        process.env.MONGODB_DB_NAME = "chat_e2e_db";
        delete process.env.MONGODB_TRAINING_DB_NAME;
        process.env.CHAT_BACKEND_URL = `http://127.0.0.1:${stubPort}`;
        process.env.CHAT_BACKEND_TOKEN = "shared-secret";
        process.env.CHAT_RATE_LIMIT_PER_IP = "1000";
        process.env.CHAT_RATE_LIMIT_PER_SESSION = "1000";
        resetChatState();
        setChatBackend(null);
        escalationWrites = [];
        setDatabaseAdapter({
            collection: (name) => ({
                findOne: async (query) =>
                    query.tenant_id === "tenant_a"
                        ? {
                              tenant_id: "tenant_a",
                              agent_config: { temperature: 0.4 },
                              widget_config: { allowed_origins: ["https://shop.example.com"] },
                          }
                        : null,
                updateOne: async (filter, update, options) => {
                    escalationWrites.push({ collection: name, filter, update, options });
                },
            }),
        });
        gateway = createApp().listen(0);
        await new Promise((resolve) => gateway.once("listening", resolve));
        gatewayUrl = `http://127.0.0.1:${gateway.address().port}`;
    });

    afterEach(async () => {
        await close(gateway);
        await close(stub);
        resetDatabaseAdapter();
        for (const key of Object.keys(process.env)) {
            if (!(key in savedEnv)) delete process.env[key];
        }
        Object.assign(process.env, savedEnv);
    });

    const send = (message, extra = {}) =>
        fetch(`${gatewayUrl}/api/chat`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                Accept: "text/event-stream",
                Origin: "https://shop.example.com",
            },
            body: JSON.stringify({ tenant_id: "tenant_a", message, session_id: SESSION }),
            ...extra,
        });

    test("streams a reply through the real backend client", async () => {
        const response = await send("How long do I have to return an item?");
        assert.equal(response.status, 200);
        const text = await response.text();
        assert.ok(text.includes('"text":"Thirty "') && text.includes('"text":"days."'));
        assert.ok(text.trimEnd().endsWith("event: done\ndata: {}"));
        assert.ok(!text.includes("LEAK"));
        assert.equal(stubRequests[0].headers["x-chat-backend-token"], "shared-secret");
        assert.equal(stubRequests[0].payload.tenant_id, "tenant_a");
        assert.equal(stubRequests[0].payload.agent_config.temperature, 0.4);
    });

    test("an escalation sent over the real service link is saved to ticket_logs with the chat log", async () => {
        const response = await send("I want a refund for a broken item");
        const text = await response.text();

        // The visitor gets the normal reply and nothing about the escalation.
        assert.ok(text.includes('"text":"Thirty "'));
        for (const leaked of ["escalat", "action", "confidence", "LEAK", "RETURNS"]) {
            assert.ok(!text.includes(leaked), `visitor stream must not contain '${leaked}'`);
        }

        // The `done` event (action: escalate) travelled back from the service and was written to ticket_logs.
        assert.equal(escalationWrites.length, 1);
        const [write] = escalationWrites;
        assert.equal(write.collection, "ticket_logs");
        assert.equal(write.options.upsert, true);
        assert.equal(write.filter.tenant_id, "tenant_a");
        assert.match(write.filter.ticket_id, /^TKT-CHAT-[0-9A-F]{12}$/);
        const saved = { ...write.update.$setOnInsert, ...write.update.$set };
        assert.equal(saved.status, "pending_review");
        assert.equal(saved.confidence, 0.4);
        assert.deepEqual(
            saved.messages.map(({ role, content }) => ({ role, content })),
            [
                { role: "customer", content: "I want a refund for a broken item" },
                { role: "agent", content: "Thirty days." },
            ]
        );
        assert.deepEqual(saved.retrieved_chunks, [{ doc_id: "RETURNS", section: "Window", score: 0.9 }]);
        assert.ok(!JSON.stringify(saved).includes("LEAK"));
    });

    test("a normal answer sent over the same link writes nothing to the database", async () => {
        await (await send("How long do I have to return an item?")).text();
        assert.deepEqual(escalationWrites, []);
    });

    test("503 service_unavailable when the chat service is down", async () => {
        await close(stub);
        stub = http.createServer();
        const response = await send("hello");
        assert.equal(response.status, 503);
        assert.equal((await response.json()).error.code, "service_unavailable");
    });

    test("503 when the chat service rejects the shared secret", async () => {
        await close(stub);
        stub = http.createServer((req, res) => {
            res.writeHead(401);
            res.end();
        });
        process.env.CHAT_BACKEND_URL = `http://127.0.0.1:${await listen(stub)}`;
        const response = await send("hello");
        assert.equal(response.status, 503);
        assert.equal((await response.json()).error.code, "service_unavailable");
    });

    test("a visitor disconnect closes the connection to the chat service", async () => {
        const controller = new AbortController();
        const response = await send("hang forever", { signal: controller.signal });
        const reader = response.body.getReader();
        await reader.read();
        controller.abort();
        await reader.cancel().catch(() => {});
        for (let i = 0; i < 200 && !upstreamClosed; i += 1) await new Promise((r) => setTimeout(r, 10));
        assert.ok(upstreamClosed, "the chat service connection should be closed so generation stops");
    });
});

describe("chat helpers", () => {
    test("SlidingWindowLimiter enforces the limit, reports Retry-After and slides", () => {
        const limiter = new SlidingWindowLimiter();
        assert.equal(limiter.hit("k", 2, 1000, 0).allowed, true);
        assert.equal(limiter.hit("k", 2, 1000, 100).allowed, true);
        const blocked = limiter.hit("k", 2, 1000, 200);
        assert.equal(blocked.allowed, false);
        assert.equal(blocked.retryAfterSec, 1);
        assert.equal(limiter.hit("other", 2, 1000, 200).allowed, true);
        assert.equal(limiter.hit("k", 2, 1000, 1001).allowed, true);
        assert.equal(limiter.hit("k", 2, 1000, 1002).allowed, false);
    });

    test("SlidingWindowLimiter stays bounded under many distinct keys", () => {
        const limiter = new SlidingWindowLimiter({ maxKeys: 50 });
        for (let i = 0; i < 500; i += 1) limiter.hit(`key-${i}`, 5, 60000, i);
        assert.ok(limiter.hits.size <= 50);
    });

    test("SessionHistory caps messages, expires, and isolates tenants", () => {
        const history = new SessionHistory({ ttlMs: 1000, maxSessions: 2 });
        for (let i = 0; i < 6; i += 1) history.add("a", "s", `q${i}`, `a${i}`, 4, 0);
        assert.deepEqual(
            history.get("a", "s", 0).map((message) => message.content),
            ["q4", "a4", "q5", "a5"]
        );
        assert.deepEqual(history.get("b", "s", 0), []);
        assert.deepEqual(history.get("a", "s", 5000), []);
        history.add("a", "1", "q", "a", 8, 0);
        history.add("a", "2", "q", "a", 8, 0);
        history.add("a", "3", "q", "a", 8, 0);
        assert.ok(history.sessions.size <= 2);
    });

    test("SessionHistory returns copies, so callers cannot mutate stored history", () => {
        const history = new SessionHistory();
        history.add("a", "s", "q", "a");
        history.get("a", "s")[0].content = "tampered";
        assert.equal(history.get("a", "s")[0].content, "q");
    });

    test("parseOriginStrict accepts bare http(s) origins only", () => {
        assert.equal(parseOriginStrict("https://Shop.Example.com"), "https://shop.example.com");
        assert.equal(parseOriginStrict("http://staging.example.com:8080/"), "http://staging.example.com:8080");
        for (const bad of [
            "*",
            "https://*.example.com",
            "https://shop.example.com/path",
            "https://shop.example.com?x=1",
            "https://user:pw@shop.example.com",
            "ftp://shop.example.com",
            "javascript:alert(1)",
            "shop.example.com",
            "",
            null,
            42,
        ]) {
            assert.equal(parseOriginStrict(bad), null, String(bad));
        }
    });

    test("parseAllowedOrigins normalizes, de-duplicates and rejects bad lists", () => {
        assert.deepEqual(parseAllowedOrigins(["https://A.example.com", "https://a.example.com/"]), {
            origins: ["https://a.example.com"],
        });
        assert.deepEqual(parseAllowedOrigins([]), { origins: [] });
        assert.ok(parseAllowedOrigins("https://a.example.com").error);
        assert.ok(parseAllowedOrigins(["*"]).error);
        assert.ok(parseAllowedOrigins(Array.from({ length: 51 }, (_, i) => `https://s${i}.example.com`)).error);
    });

    test("resolveAllowedOrigins fails closed and isOriginAllowed treats a missing Origin as non-browser", () => {
        const defaults = ["https://default.example.com"];
        assert.deepEqual([...resolveAllowedOrigins({}, defaults)], ["https://default.example.com"]);
        assert.deepEqual([...resolveAllowedOrigins({}, [])], []);
        assert.deepEqual([...resolveAllowedOrigins({ widget_config: { allowed_origins: [] } }, defaults)], []);
        assert.deepEqual(
            [...resolveAllowedOrigins({ widget_config: { allowed_origins: ["*", "https://ok.example.com", 5] } }, defaults)],
            ["https://ok.example.com"]
        );
        const allowed = new Set(["https://ok.example.com"]);
        assert.equal(isOriginAllowed(undefined, allowed), true);
        assert.equal(isOriginAllowed("https://ok.example.com", allowed), true);
        assert.equal(isOriginAllowed("https://other.example.com", allowed), false);
        assert.equal(isOriginAllowed("null", allowed), false);
    });

    test("getChatConfig reads environment values and ignores invalid ones", () => {
        const config = getChatConfig({
            CHAT_BACKEND_URL: "http://chat:8100/",
            CHAT_RATE_LIMIT_PER_IP: "5",
            CHAT_RATE_LIMIT_PER_SESSION: "abc",
            CHAT_RATE_LIMIT_WINDOW_MS: "-1",
            WIDGET_DEFAULT_ALLOWED_ORIGINS: " https://a.example.com , https://b.example.com ",
        });
        assert.equal(config.backendUrl, "http://chat:8100");
        assert.equal(config.rateLimitPerIp, 5);
        assert.equal(config.rateLimitPerSession, 10);
        assert.equal(config.rateLimitWindowMs, 60000);
        assert.deepEqual(config.defaultAllowedOrigins, ["https://a.example.com", "https://b.example.com"]);
        // No built-in default: unset or empty means no origin is allowed for tenants without a list.
        assert.deepEqual(getChatConfig({}).defaultAllowedOrigins, []);
        assert.deepEqual(getChatConfig({ WIDGET_DEFAULT_ALLOWED_ORIGINS: "  " }).defaultAllowedOrigins, []);
    });

    test("buildAgentConfig clamps out-of-range and wrongly typed values", () => {
        assert.deepEqual(
            buildAgentConfig({
                system_prompt: "  hi  ",
                agent_tone: 5,
                temperature: 9,
                max_context_chunks: 99,
                similarity_threshold: -3,
            }),
            { system_prompt: "hi", agent_tone: "", temperature: 1, max_context_chunks: 8, similarity_threshold: 0 }
        );
        assert.deepEqual(buildAgentConfig(null), {
            system_prompt: "",
            agent_tone: "",
            temperature: 0.2,
            max_context_chunks: 4,
            similarity_threshold: 0.7,
        });
    });
});
