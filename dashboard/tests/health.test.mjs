import { test } from "node:test";
import assert from "node:assert/strict";
import {
    HEALTH_POLL_FAST_MS,
    HEALTH_POLL_SLOW_MS,
    describeVectorIndex,
    nextHealthPollDelay,
} from "../src/lib/health.mjs";

const health = (state, extra = {}) => ({
    vector_index_ready: state === "ready",
    vector_index_state: state,
    vector_index: { name: "vector_index", state, ...extra },
    ollama_ready: true,
});

test("shows the real state instead of collapsing everything to not_ready", () => {
    for (const state of ["missing", "building", "ready", "unknown", "failed", "misconfigured", "permission_denied"]) {
        assert.equal(describeVectorIndex(health(state)).label, state);
    }
});

test("tones: ready ok, building pending, missing and permission errors red, unknown neutral", () => {
    assert.equal(describeVectorIndex(health("ready")).tone, "ok");
    assert.equal(describeVectorIndex(health("building")).tone, "pending");
    assert.equal(describeVectorIndex(health("missing")).tone, "error");
    assert.equal(describeVectorIndex(health("permission_denied")).tone, "error");
    assert.equal(describeVectorIndex(health("unknown")).tone, "unknown");
});

test("shows the gateway's own message when it sends one, and a default otherwise", () => {
    assert.equal(
        describeVectorIndex(health("permission_denied", { message: "Grant the role X." })).message,
        "Grant the role X."
    );
    assert.match(describeVectorIndex(health("missing")).message, /No vector index/);
    assert.equal(describeVectorIndex(health("ready", { message: "ignored" })).message, "");
});

test("an older gateway that only sends the boolean still renders", () => {
    assert.equal(describeVectorIndex({ vector_index_ready: true }).label, "ready");
    assert.equal(describeVectorIndex({ vector_index_ready: false }).label, "unknown");
    assert.equal(describeVectorIndex({ vector_index_state: "something-new" }).label, "unknown");
    assert.equal(describeVectorIndex(null), null);
});

test("polls quickly while not ready or when the gateway is unreachable, slowly once everything is ready", () => {
    assert.equal(nextHealthPollDelay(health("building")), HEALTH_POLL_FAST_MS);
    assert.equal(nextHealthPollDelay(health("missing")), HEALTH_POLL_FAST_MS);
    assert.equal(nextHealthPollDelay(null, true), HEALTH_POLL_FAST_MS);
    assert.equal(nextHealthPollDelay(health("ready")), HEALTH_POLL_SLOW_MS);
    assert.equal(nextHealthPollDelay({ ...health("ready"), ollama_ready: false }), HEALTH_POLL_FAST_MS);
});
