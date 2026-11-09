import assert from "node:assert/strict";
import test, { after, before } from "node:test";
import { createMockApp } from "../mock/mock_gateway.js";
import { streamChat } from "../src/lib/chatClient.js";

let server;
let apiUrl;

before(async () => {
    server = createMockApp({ tokenDelayMs: 1 }).listen(0);
    await new Promise((resolve) => server.once("listening", resolve));
    apiUrl = `http://127.0.0.1:${server.address().port}`;
});

after(() => {
    server.closeAllConnections?.();
    server.close();
});

const call = (message, extra = {}) =>
    streamChat({ apiUrl, tenantId: "example_tenant", message, sessionId: "s1", ...extra });

test("contract: streaming reply delivers only tokens and done", async () => {
    const tokens = [];
    const result = await call("What is your return policy?", { onToken: (t) => tokens.push(t) });
    assert.ok(tokens.length > 1, "expected multiple token events");
    assert.equal(result.answer, tokens.join(""));
    assert.match(result.answer, /return policy/);
    assert.deepEqual(Object.keys(result).sort(), ["answer", "sessionId"]);
});

test("contract: the raw stream contains no sources and no escalation signal", async () => {
    const response = await fetch(`${apiUrl}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify({ tenant_id: "t", message: "hi", session_id: "s" }),
    });
    const text = await response.text();
    const events = [...text.matchAll(/^event: (.*)$/gm)].map((match) => match[1]);
    assert.ok(events.length > 2);
    assert.deepEqual([...new Set(events)].sort(), ["done", "token"]);
    for (const leaked of ["sources", "doc_id", "escalat", "action", "confidence"]) {
        assert.ok(!text.toLowerCase().includes(leaked), `stream must not contain '${leaked}'`);
    }
});

test("contract: real SSE content type and anti-buffering headers", async () => {
    const response = await fetch(`${apiUrl}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify({ tenant_id: "t", message: "hi", session_id: "s" }),
    });
    assert.match(response.headers.get("content-type"), /^text\/event-stream/);
    assert.match(response.headers.get("cache-control"), /no-cache/);
    assert.equal(response.headers.get("x-accel-buffering"), "no");
    await response.body.cancel();
});

test("contract: JSON fallback when the client does not accept SSE", async () => {
    const response = await fetch(`${apiUrl}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ tenant_id: "t", message: "hi", session_id: "s" }),
    });
    const body = await response.json();
    assert.match(response.headers.get("content-type"), /application\/json/);
    assert.equal(typeof body.answer, "string");
    assert.equal(body.session_id, "s");
});

test("contract: nostream keyword yields JSON that the client still handles", async () => {
    const result = await call("nostream please");
    assert.match(result.answer, /nostream please/);
    assert.deepEqual(Object.keys(result).sort(), ["answer", "sessionId"]);
});

test("contract: the JSON fallback body has only answer and session_id", async () => {
    const response = await fetch(`${apiUrl}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ tenant_id: "t", message: "hi", session_id: "s" }),
    });
    assert.deepEqual(Object.keys(await response.json()).sort(), ["answer", "session_id"]);
});

test("contract: validation errors use the error envelope", async () => {
    const response = await fetch(`${apiUrl}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tenant_id: "t", session_id: "s" }),
    });
    assert.equal(response.status, 400);
    assert.equal((await response.json()).error.code, "invalid_request");

    const tooLong = await fetch(`${apiUrl}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tenant_id: "t", session_id: "s", message: "x".repeat(2001) }),
    });
    assert.equal(tooLong.status, 400);
    assert.equal((await tooLong.json()).error.code, "message_too_long");
});

test("contract: 429 and 404 surface as ChatError", async () => {
    await assert.rejects(call("ratelimit"), (e) => e.code === "rate_limited" && e.status === 429);
    await assert.rejects(call("unknown tenant"), (e) => e.code === "unknown_tenant" && e.status === 404);
});

test("contract: mid-stream error and missing done are reported", async () => {
    const tokens = [];
    await assert.rejects(call("error", { onToken: (t) => tokens.push(t) }), (e) => e.code === "generation_failed");
    assert.ok(tokens.length > 0, "tokens should arrive before the failure");
    await assert.rejects(call("cutoff"), (e) => e.code === "stream_interrupted");
});

test("contract: CORS preflight allows cross-origin POST without credentials", async () => {
    const response = await fetch(`${apiUrl}/api/chat`, {
        method: "OPTIONS",
        headers: {
            Origin: "https://shop.example.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    });
    assert.ok(response.status < 300);
    assert.ok(response.headers.get("access-control-allow-origin"));
    assert.notEqual(response.headers.get("access-control-allow-credentials"), "true");
});

test("aborting mid-stream stops the client", async () => {
    const controller = new AbortController();
    const pending = call("slow answer", {
        signal: controller.signal,
        onToken: () => controller.abort(),
    });
    await assert.rejects(pending, (e) => e.code === "aborted");
});

test("contract: follow-up capability supports SSE and JSON and scopes contact saving", async () => {
    const { submitContact } = await import("../src/lib/chatClient.js");
    for (const message of ["human please", "human nostream please"]) {
        const result = await call(message);
        assert.equal(result.followUp.available, true);
        assert.equal(typeof result.followUp.token, "string");
        assert.equal(result.followUp.contactEmail, "support@example.test");
        const options = { apiUrl, tenantId: "example_tenant", sessionId: "s1", followUpToken: result.followUp.token,
            name: "Test Visitor", email: "visitor@example.test" };
        assert.deepEqual(await submitContact(options), { status: "saved" });
        await assert.rejects(submitContact({ ...options, sessionId: "other" }), (error) => error.status === 403);
        await assert.rejects(submitContact({ ...options, tenantId: "other" }), (error) => error.status === 403);
    }
});
