/**
 * Environment-driven settings for the public chat endpoint (POST /api/chat).
 * Read at request time so deployments and tests can change them without a restart.
 */

function intFromEnv(env, name, fallback, { min = 1, max = Number.MAX_SAFE_INTEGER } = {}) {
    const raw = env[name];
    if (raw === undefined || raw === null || String(raw).trim() === "") {
        return fallback;
    }
    const value = Number(raw);
    if (!Number.isInteger(value) || value < min || value > max) {
        return fallback;
    }
    return value;
}

function listFromEnv(env, name, fallback) {
    const raw = env[name];
    if (raw === undefined || raw === null) {
        return fallback;
    }
    return String(raw)
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean);
}

function getChatConfig(env = process.env) {
    return {
        backendUrl: String(env.CHAT_BACKEND_URL || "http://127.0.0.1:8100").trim().replace(/\/+$/, ""),
        backendToken: String(env.CHAT_BACKEND_TOKEN || ""),
        rateLimitPerIp: intFromEnv(env, "CHAT_RATE_LIMIT_PER_IP", 30),
        rateLimitPerSession: intFromEnv(env, "CHAT_RATE_LIMIT_PER_SESSION", 10),
        rateLimitWindowMs: intFromEnv(env, "CHAT_RATE_LIMIT_WINDOW_MS", 60 * 1000),
        maxDurationMs: intFromEnv(env, "CHAT_MAX_DURATION_MS", 120 * 1000),
        heartbeatMs: intFromEnv(env, "CHAT_HEARTBEAT_MS", 10 * 1000),
        historyMaxMessages: intFromEnv(env, "CHAT_HISTORY_MAX_MESSAGES", 8, { max: 12 }),
        // Origins for tenants that have no allowed-origins list of their own. There is no built-in
        // default: when WIDGET_DEFAULT_ALLOWED_ORIGINS is unset or empty, such tenants reject every
        // browser origin. Local-development values belong in .env, not in code.
        defaultAllowedOrigins: listFromEnv(env, "WIDGET_DEFAULT_ALLOWED_ORIGINS", []),
    };
}

module.exports = { getChatConfig };
