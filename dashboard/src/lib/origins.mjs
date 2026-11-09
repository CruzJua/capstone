/**
 * Helpers for the "Allowed widget origins" field (businesses.widget_config.allowed_origins).
 * The gateway is the authority on validity (exact http(s) origins, no wildcards or paths); this only
 * turns the textarea into a clean list and keeps harmless typos such as a trailing slash out of the way.
 */

/** One origin per line (commas and spaces also separate). Trims, drops a trailing slash, removes duplicates. */
export function parseOriginsInput(text) {
    const seen = new Set();
    const origins = [];
    for (const raw of String(text || "").split(/[\s,]+/)) {
        const entry = raw.trim().replace(/\/+$/, "");
        if (entry && !seen.has(entry)) {
            seen.add(entry);
            origins.push(entry);
        }
    }
    return origins;
}

export function originsToText(origins) {
    return Array.isArray(origins) ? origins.filter((o) => typeof o === "string").join("\n") : "";
}

/**
 * The payload fragment to send on save. It is omitted unless the admin changed the field: a tenant
 * that has never set origins falls back to the gateway's defaults, and saving an untouched empty
 * box must not silently turn that into "allow no site at all".
 */
export function widgetConfigPayload(currentText, savedText) {
    const current = parseOriginsInput(currentText);
    const saved = parseOriginsInput(savedText);
    if (current.length === saved.length && current.every((origin, index) => origin === saved[index])) {
        return undefined;
    }
    return { allowed_origins: current };
}
