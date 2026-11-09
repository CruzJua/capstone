const memoryStore = new Map();

function generateId() {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
        return crypto.randomUUID();
    }
    return `s_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 12)}`;
}

function defaultStorage() {
    try {
        return typeof localStorage !== "undefined" ? localStorage : null;
    } catch {
        return null;
    }
}

/**
 * Returns a stable per-tenant visitor session id. Uses localStorage when it is
 * available and falls back to in-memory storage (private windows, blocked storage).
 */
export function getSessionId(tenantId, storage = defaultStorage()) {
    const key = `support_widget_session:${tenantId}`;
    if (memoryStore.has(key)) return memoryStore.get(key);
    try {
        const existing = storage ? storage.getItem(key) : null;
        if (existing) {
            memoryStore.set(key, existing);
            return existing;
        }
    } catch {
        // fall through to memory
    }
    if (memoryStore.has(key)) {
        return memoryStore.get(key);
    }
    const id = generateId();
    memoryStore.set(key, id);
    try {
        if (storage) {
            storage.setItem(key, id);
        }
    } catch {
        // memory copy is enough
    }
    return id;
}

/** Test helper: clears the in-memory fallback. */
export function resetSessionMemory() {
    memoryStore.clear();
}

/** Starts and persists a fresh conversation; existing server history is untouched. */
export function newSessionId(tenantId, storage = defaultStorage()) {
    const key = `support_widget_session:${tenantId}`;
    const id = generateId();
    memoryStore.set(key, id);
    try { storage?.setItem(key, id); } catch { /* private-window fallback */ }
    return id;
}
