import assert from "node:assert/strict";
import test from "node:test";
import { ChatError, streamChat } from "../src/lib/chatClient.js";

const encoder = new TextEncoder();

function sseResponse(chunks, { status = 200 } = {}) {
    const stream = new ReadableStream({
        start(controller) {
            for (const chunk of chunks) {
                controller.enqueue(encoder.encode(chunk));
            }
            controller.close();
        },
    });
    return new Response(stream, { status, headers: { "Content-Type": "text/event-stream" } });
}

function jsonResponse(body, status = 200) {
    return new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
    });
}

const base = { apiUrl: "http://gw.test/", tenantId: "example_tenant", message: "hello", sessionId: "s1" };

test("sends the documented request", async () => {
    let captured;
    await streamChat({
        ...base,
        fetchImpl: async (url, init) => {
            captured = { url, init };
            return sseResponse(["event: done\ndata: {}\n\n"]);
        },
    });
    assert.equal(captured.url, "http://gw.test/api/chat");
    assert.equal(captured.init.method, "POST");
    assert.match(captured.init.headers.Accept, /text\/event-stream/);
    assert.deepEqual(JSON.parse(captured.init.body), {
        tenant_id: "example_tenant",
        message: "hello",
        session_id: "s1",
    });
    assert.equal(captured.init.credentials, undefined);
});

test("streams only the model's tokens, split across arbitrary chunk boundaries", async () => {
    const wire =
        'event: token\ndata: {"text":"Hello "}\n\n' +
        'event: token\ndata: {"text":"world"}\n\n' +
        "event: done\ndata: {}\n\n";
    const chunks = wire.match(/[\s\S]{1,7}/g);
    const tokens = [];
    const result = await streamChat({
        ...base,
        fetchImpl: async () => sseResponse(chunks),
        onToken: (t) => tokens.push(t),
    });
    assert.deepEqual(tokens, ["Hello ", "world"]);
    assert.deepEqual(result, { answer: "Hello world", sessionId: "s1" });
});

test("ignores a legacy `sources` event from an older gateway: the visitor never gets sources", async () => {
    const wire =
        'event: sources\ndata: {"sources":[{"doc_id":"A","section":"S","score":0.9}]}\n\n' +
        'event: token\ndata: {"text":"Hi"}\n\n' +
        "event: done\ndata: {}\n\n";
    const tokens = [];
    const result = await streamChat({
        ...base,
        fetchImpl: async () => sseResponse([wire]),
        onToken: (t) => tokens.push(t),
    });
    assert.deepEqual(tokens, ["Hi"]);
    assert.deepEqual(Object.keys(result).sort(), ["answer", "sessionId"]);
    assert.ok(!JSON.stringify(result).includes("doc_id"));
});

test("falls back to a single JSON body when the response is not an event stream", async () => {
    const tokens = [];
    const result = await streamChat({
        ...base,
        fetchImpl: async () => jsonResponse({ answer: "Full answer", session_id: "s9" }),
        onToken: (t) => tokens.push(t),
    });
    assert.deepEqual(tokens, ["Full answer"]);
    assert.deepEqual(result, { answer: "Full answer", sessionId: "s9" });
});

test("a legacy `sources` field in a JSON reply is ignored", async () => {
    const result = await streamChat({
        ...base,
        fetchImpl: async () => jsonResponse({ answer: "Full answer", sources: [{ doc_id: "A" }], session_id: "s9" }),
    });
    assert.deepEqual(result, { answer: "Full answer", sessionId: "s9" });
});

test("maps HTTP errors to ChatError with the gateway's code and message", async () => {
    await assert.rejects(
        streamChat({
            ...base,
            fetchImpl: async () =>
                jsonResponse({ error: { code: "rate_limited", message: "Slow down" } }, 429),
        }),
        (err) => err instanceof ChatError && err.code === "rate_limited" && err.status === 429 && err.message === "Slow down"
    );
});

test("handles a non-JSON error body", async () => {
    await assert.rejects(
        streamChat({ ...base, fetchImpl: async () => new Response("<html>bad gateway</html>", { status: 502 }) }),
        (err) => err.code === "http_502"
    );
});

test("raises an in-stream error event after partial tokens", async () => {
    const tokens = [];
    await assert.rejects(
        streamChat({
            ...base,
            fetchImpl: async () =>
                sseResponse([
                    'event: token\ndata: {"text":"Par"}\n\n',
                    'event: error\ndata: {"code":"generation_failed","message":"boom"}\n\n',
                ]),
            onToken: (t) => tokens.push(t),
        }),
        (err) => err.code === "generation_failed" && err.message === "boom"
    );
    assert.deepEqual(tokens, ["Par"]);
});

test("treats a stream that ends without done as interrupted", async () => {
    await assert.rejects(
        streamChat({
            ...base,
            fetchImpl: async () => sseResponse(['event: token\ndata: {"text":"Par"}\n\n']),
        }),
        (err) => err.code === "stream_interrupted"
    );
});

test("reports network failures", async () => {
    await assert.rejects(
        streamChat({
            ...base,
            fetchImpl: async () => {
                throw new TypeError("Failed to fetch");
            },
        }),
        (err) => err.code === "network_error"
    );
});

test("caller abort cancels the request and reports 'aborted'", async () => {
    const controller = new AbortController();
    const fetchImpl = (url, init) =>
        new Promise((resolve, reject) => {
            init.signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
        });
    const pending = streamChat({ ...base, signal: controller.signal, fetchImpl });
    controller.abort();
    await assert.rejects(pending, (err) => err.code === "aborted");
});

test("an already-aborted signal rejects immediately without calling fetch", async () => {
    const controller = new AbortController();
    controller.abort();
    let called = false;
    await assert.rejects(
        streamChat({
            ...base,
            signal: controller.signal,
            fetchImpl: async () => {
                called = true;
            },
        }),
        (err) => err.code === "aborted"
    );
    assert.equal(called, false);
});

test("times out when the gateway goes silent", async () => {
    const fetchImpl = (url, init) =>
        new Promise((resolve, reject) => {
            init.signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
        });
    await assert.rejects(
        streamChat({ ...base, fetchImpl, idleTimeoutMs: 30 }),
        (err) => err.code === "timeout"
    );
});
