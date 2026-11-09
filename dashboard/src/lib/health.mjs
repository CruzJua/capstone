/**
 * Turns the gateway's /api/health payload into what the sidebar shows.
 * Plain JavaScript with no imports so it can be unit-tested with `node --test`.
 */

/** While the index is not ready (or the gateway is unreachable) health is re-checked this often. */
export const HEALTH_POLL_FAST_MS = 5000;
/** Once everything is ready, a slow poll still notices a later outage. */
export const HEALTH_POLL_SLOW_MS = 60000;

const KNOWN_STATES = new Set([
    "ready",
    "building",
    "missing",
    "failed",
    "misconfigured",
    "permission_denied",
    "unknown",
    "skipped",
]);

const DEFAULT_MESSAGES = {
    ready: "",
    building: "The vector index is building. Search works once it is ready.",
    missing: "No vector index exists yet. It is created on gateway start or on the first document upload.",
    failed: "The vector index build failed. Check the index in Atlas.",
    misconfigured: "The vector index does not match the expected definition.",
    permission_denied: "The database user cannot create search indexes. Grant it the required Atlas role.",
    unknown: "The vector index state could not be read.",
    skipped: "Vector index setup was skipped.",
};

/**
 * @returns {null | { state: string, label: string, tone: "ok"|"pending"|"error"|"unknown", message: string, ready: boolean }}
 */
export function describeVectorIndex(health) {
    if (!health || typeof health !== "object") {
        return null;
    }
    let state = health.vector_index_state;
    if (typeof state !== "string" || !KNOWN_STATES.has(state)) {
        // Older gateways only send the boolean.
        state = health.vector_index_ready === true ? "ready" : "unknown";
    }
    const detail = health.vector_index && typeof health.vector_index === "object" ? health.vector_index : {};
    const message =
        state === "ready"
            ? ""
            : (typeof detail.message === "string" && detail.message.trim()) || DEFAULT_MESSAGES[state] || "";

    let tone = "unknown";
    if (state === "ready") tone = "ok";
    else if (state === "building") tone = "pending";
    else if (["missing", "failed", "misconfigured", "permission_denied"].includes(state)) tone = "error";

    return { state, label: state, tone, message, ready: state === "ready" };
}

/** How long to wait before the next health check. `failed` means the last request did not succeed. */
export function nextHealthPollDelay(health, failed = false) {
    if (failed) return HEALTH_POLL_FAST_MS;
    const index = describeVectorIndex(health);
    const ollamaReady = !health || health.ollama_ready !== false;
    return index && index.ready && ollamaReady ? HEALTH_POLL_SLOW_MS : HEALTH_POLL_FAST_MS;
}
