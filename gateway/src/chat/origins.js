/**
 * Per-tenant allowed-origins list for the embeddable widget.
 *
 * Stored on the businesses document as `widget_config.allowed_origins` (array of exact origins such
 * as "https://shop.example.com"; no wildcards, no paths). A tenant without that field falls back to
 * WIDGET_DEFAULT_ALLOWED_ORIGINS, which has no built-in value: unset means every browser origin is
 * rejected. An explicitly empty array also allows no browser origin at all.
 */

const MAX_ALLOWED_ORIGINS = 50;

// DNS labels (letters, digits, inner hyphens) or a bracketed IPv6 literal. The WHATWG URL parser
// would otherwise accept characters such as "*" in a host, which must never pass as an exact origin.
const HOSTNAME_PATTERN =
    /^(\[[0-9a-f:.]+\]|[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*)$/;

/** Returns the canonical origin for a bare http(s) origin string, or null if it is not one. */
function parseOriginStrict(value) {
    if (typeof value !== "string") return null;
    let url;
    try {
        url = new URL(value.trim());
    } catch {
        return null;
    }
    if (url.protocol !== "http:" && url.protocol !== "https:") return null;
    if (url.username || url.password || url.search || url.hash) return null;
    if (url.pathname !== "/") return null;
    if (!HOSTNAME_PATTERN.test(url.hostname.toLowerCase())) return null;
    return url.origin.toLowerCase();
}

/** Validates an admin-supplied list. Returns { origins } or { error }. */
function parseAllowedOrigins(value) {
    if (!Array.isArray(value)) {
        return { error: "widget_config.allowed_origins must be an array of origins." };
    }
    if (value.length > MAX_ALLOWED_ORIGINS) {
        return { error: `widget_config.allowed_origins may contain at most ${MAX_ALLOWED_ORIGINS} origins.` };
    }
    const origins = [];
    for (const entry of value) {
        const origin = parseOriginStrict(entry);
        if (!origin) {
            return {
                error: "widget_config.allowed_origins entries must be exact http(s) origins such as https://shop.example.com (no wildcards, paths or credentials).",
            };
        }
        if (!origins.includes(origin)) origins.push(origin);
    }
    return { origins };
}

/** Effective allowed origins for a tenant document. Invalid stored entries are ignored (fail closed). */
function resolveAllowedOrigins(tenant, defaults) {
    const configured = tenant && tenant.widget_config && tenant.widget_config.allowed_origins;
    const source = Array.isArray(configured) ? configured : defaults;
    const resolved = new Set();
    for (const entry of source) {
        const origin = parseOriginStrict(entry);
        if (origin) resolved.add(origin);
    }
    return resolved;
}

/**
 * A request without an Origin header is not a browser cross-site request (curl, server-side
 * callers), so the origin allowlist does not apply to it; rate limits and tenant scoping still do.
 * A browser page that sends an Origin must be on the list ("null" origins are never allowed).
 */
function isOriginAllowed(originHeader, allowedOrigins) {
    if (originHeader === undefined || originHeader === null || originHeader === "") {
        return true;
    }
    const origin = parseOriginStrict(String(originHeader));
    return origin !== null && allowedOrigins.has(origin);
}

module.exports = {
    MAX_ALLOWED_ORIGINS,
    parseOriginStrict,
    parseAllowedOrigins,
    resolveAllowedOrigins,
    isOriginAllowed,
};
