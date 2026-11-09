/**
 * Bounded in-memory conversation memory for the widget, keyed by (tenant_id, session_id).
 * The tenant is part of the key, so one tenant's session id can never read another tenant's turns.
 * Nothing is persisted here; entries disappear on restart or after the idle TTL. (A conversation is
 * only written to the database when the assistant escalates it to a human; see escalation.js.)
 *
 * Two views of the same conversation:
 *   get()           the short recent window sent to the model as context
 *   getTranscript() the longer, timestamped record a human reviewer sees on an escalation ticket
 */
const MAX_CONTENT_LENGTH = 2000;
const MAX_TRANSCRIPT_MESSAGES = 40;

class SessionHistory {
    constructor({ maxSessions = 1000, ttlMs = 30 * 60 * 1000 } = {}) {
        this.maxSessions = maxSessions;
        this.ttlMs = ttlMs;
        this.sessions = new Map();
    }

    key(tenantId, sessionId) {
        return `${tenantId}\u0000${sessionId}`;
    }

    live(tenantId, sessionId, now) {
        const key = this.key(tenantId, sessionId);
        const entry = this.sessions.get(key);
        if (!entry) return null;
        if (now - entry.touchedAt > this.ttlMs) {
            this.sessions.delete(key);
            return null;
        }
        return entry;
    }

    /** Recent turns for the model: [{ role: "user" | "assistant", content }]. */
    get(tenantId, sessionId, now = Date.now()) {
        const entry = this.live(tenantId, sessionId, now);
        if (!entry) return [];
        return entry.messages.map(({ role, content }) => ({ role, content }));
    }

    /** Whole retained conversation, oldest first: [{ role, content, timestamp }]. */
    getTranscript(tenantId, sessionId, now = Date.now()) {
        const entry = this.live(tenantId, sessionId, now);
        if (!entry) return [];
        return entry.transcript.map((message) => ({ ...message }));
    }

    add(tenantId, sessionId, userText, assistantText, maxMessages = 8, now = Date.now()) {
        const key = this.key(tenantId, sessionId);
        const existing = this.live(tenantId, sessionId, now);
        const messages = existing ? existing.messages : [];
        const transcript = existing ? existing.transcript : [];
        const timestamp = new Date(now).toISOString();
        const turn = [
            { role: "user", content: String(userText).slice(0, MAX_CONTENT_LENGTH), timestamp },
            { role: "assistant", content: String(assistantText).slice(0, MAX_CONTENT_LENGTH), timestamp },
        ];
        messages.push(...turn);
        transcript.push(...turn);
        while (messages.length > maxMessages) {
            messages.shift();
        }
        while (transcript.length > MAX_TRANSCRIPT_MESSAGES) {
            transcript.shift();
        }
        // Re-insert so Map iteration order approximates least-recently-used.
        this.sessions.delete(key);
        if (this.sessions.size >= this.maxSessions) {
            const oldestKey = this.sessions.keys().next().value;
            if (oldestKey !== undefined) this.sessions.delete(oldestKey);
        }
        this.sessions.set(key, { messages, transcript, touchedAt: now });
        return turn[1];
    }

    reset() {
        this.sessions.clear();
    }
}

module.exports = { SessionHistory, MAX_TRANSCRIPT_MESSAGES };
