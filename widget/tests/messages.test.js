import { test } from "node:test";
import assert from "node:assert/strict";
import { ChatError, streamChat } from "../src/lib/chatClient.js";
import { isRetryable, visitorMessage } from "../src/lib/messages.js";

const UNSAFE = /traceback|stack|mongo|ollama|exception|undefined|internal|localhost|127\.0\.0\.1|token/i;

test("every known failure maps to a specific, safe message", () => {
    const codes = [
        "network_error",
        "timeout",
        "stream_interrupted",
        "generation_failed",
        "stream_error",
        "service_unavailable",
        "rate_limited",
        "message_too_long",
        "invalid_request",
        "unknown_tenant",
        "origin_not_allowed",
    ];
    const seen = new Set();
    for (const code of codes) {
        const text = visitorMessage(new ChatError(code, "server said: Traceback at mongo://internal"));
        assert.ok(text.length > 10, code);
        assert.doesNotMatch(text, UNSAFE, code);
        assert.ok(!text.includes("server said"), `${code} must not echo the server's text`);
        seen.add(text);
    }
    // Two pairs share a message on purpose (generation_failed/stream_error and unknown_tenant/
    // origin_not_allowed); everything else is distinct.
    assert.equal(seen.size, codes.length - 2);
});

test("backend failures read as 'temporarily unavailable'", () => {
    const text = visitorMessage(new ChatError("service_unavailable", "x", 503));
    assert.match(text, /temporarily unavailable/);
    assert.match(visitorMessage(new ChatError("http_502", "x", 502)), /temporarily unavailable/);
});

test("unknown codes fall back to a generic message, never the server's text", () => {
    const text = visitorMessage(new ChatError("weird_code", "Error: ECONNREFUSED 10.0.0.5:27017", 400));
    assert.equal(text, "Something went wrong. Please try again.");
    assert.equal(visitorMessage(undefined), "Something went wrong. Please try again.");
});

test("retry is offered when it can help and hidden when it cannot", () => {
    for (const code of ["network_error", "timeout", "stream_interrupted", "generation_failed", "service_unavailable", "rate_limited"]) {
        assert.equal(isRetryable(new ChatError(code, "x")), true, code);
    }
    for (const code of ["message_too_long", "invalid_request", "unknown_tenant", "origin_not_allowed"]) {
        assert.equal(isRetryable(new ChatError(code, "x")), false, code);
    }
    assert.equal(isRetryable(new ChatError("http_503", "x", 503)), true);
});

test("rate limit message uses Retry-After", () => {
    assert.match(visitorMessage(new ChatError("rate_limited", "x", 429, 12)), /wait 12 seconds/);
    assert.match(visitorMessage(new ChatError("rate_limited", "x", 429, 60)), /wait 60 seconds/);
    assert.match(visitorMessage(new ChatError("rate_limited", "x", 429, 180)), /wait 3 minutes/);
    assert.match(visitorMessage(new ChatError("rate_limited", "x", 429)), /wait a moment/);
});

test("streamChat carries the Retry-After header on a 429", async () => {
    const fetchImpl = async () =>
        new Response(JSON.stringify({ error: { code: "rate_limited", message: "Slow down" } }), {
            status: 429,
            headers: { "Content-Type": "application/json", "Retry-After": "42" },
        });
    await assert.rejects(
        streamChat({ apiUrl: "http://gw.test", tenantId: "example_tenant", message: "hi", sessionId: "s1", fetchImpl }),
        (error) => error.code === "rate_limited" && error.retryAfterSec === 42 && error.status === 429
    );
});
