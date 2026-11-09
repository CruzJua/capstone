/**
 * Human escalation for the public chat endpoint.
 *
 * When the model decides a question needs a person (action "escalate"), the gateway saves the
 * conversation as a ticket in ticket_logs, in the schema the dashboard's review queue already reads
 * (status "pending_review", messages[], escalation_reason, ticket_summary, retrieved_chunks, ...).
 *
 * After persistence the route may issue a scoped follow-up capability to the visitor. Retrieval
 * details (document ids, sections, scores) and confidence go to the reviewer on the ticket only.
 *
 * One ticket per (tenant, conversation): the id is a hash of both, so a visitor who escalates twice
 * updates the same ticket, with the full transcript, instead of opening duplicates. The visitor's raw
 * session id is never stored.
 */
const crypto = require("crypto");
const { getTicketLogsCollection } = require("../db/mongo");

const SAVE_TIMEOUT_MS = 5000;
const MAX_CITED_SOURCES = 20;

function buildEscalationTicketId(tenantId, sessionId) {
    const digest = crypto.createHash("sha256").update(`${tenantId}\u0000${sessionId}`).digest("hex");
    return `TKT-CHAT-${digest.slice(0, 12).toUpperCase()}`;
}

function isEscalation(doneEvent) {
    return Boolean(doneEvent) && doneEvent.action === "escalate";
}

function truncate(text, max) {
    const value = String(text);
    return value.length > max ? `${value.slice(0, max - 1)}…` : value;
}

/** Builds the ticket document. `sources` are the sanitized { doc_id, section, score } entries. */
function buildEscalationTicket({ tenantId, sessionId, message, answer, done, sources, transcript, now = new Date() }) {
    const nowIso = now.toISOString();
    const chunks = Array.isArray(sources) ? sources : [];
    const escalationReason = chunks.length === 0 ? "not_in_docs" : "docs_require_human";
    const confidence =
        done && typeof done.confidence === "number" && Number.isFinite(done.confidence)
            ? Math.min(1, Math.max(0, done.confidence))
            : null;
    const citedSources = (Array.isArray(done && done.cited_sources) ? done.cited_sources : [])
        .filter((entry) => typeof entry === "string")
        .slice(0, MAX_CITED_SOURCES)
        .map((entry) => truncate(entry, 200));

    const turns =
        Array.isArray(transcript) && transcript.length > 0
            ? transcript
            : [
                  { role: "user", content: message, timestamp: nowIso },
                  { role: "assistant", content: answer, timestamp: nowIso },
              ];
    const messages = turns.map((turn) => ({
        role: turn.role === "user" ? "customer" : "agent",
        content: turn.content,
        timestamp: turn.timestamp || nowIso,
    }));

    const reasonText =
        escalationReason === "not_in_docs"
            ? "No relevant documentation was found for this question."
            : "The assistant judged that this needs a person.";
    const confidenceText = confidence === null ? "" : ` (confidence ${confidence.toFixed(2)})`;

    return {
        ticket_id: buildEscalationTicketId(tenantId, sessionId),
        tenant_id: tenantId,
        question: message,
        answer,
        rationale: "",
        similarity_score: chunks.reduce((best, chunk) => Math.max(best, chunk.score || 0), 0),
        retrieved_chunks: chunks,
        status: "pending_review",
        escalation_reason: escalationReason,
        ticket_summary: `Escalated by the assistant${confidenceText}. Visitor asked: "${truncate(message, 200)}". ${reasonText}`,
        customer_contact: { name: "", email: "" },
        messages,
        admin_notes: "",
        channel: "widget",
        confidence,
        cited_sources: citedSources,
        created_at: nowIso,
        updated_at: nowIso,
    };
}

function withTimeout(promise, timeoutMs) {
    let timer;
    const timeout = new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error("Escalation save timed out.")), timeoutMs);
        if (typeof timer.unref === "function") timer.unref();
    });
    return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
}

/**
 * Inserts the ticket, or updates the existing one for this conversation. A new escalation re-opens
 * a ticket that was resolved, while admin_notes and any contact details an admin added are kept.
 */
async function saveEscalationTicket(ticket, { timeoutMs = SAVE_TIMEOUT_MS } = {}) {
    const { ticket_id: ticketId, tenant_id: tenantId, created_at: createdAt, admin_notes, customer_contact, ...latest } = ticket;
    const result = await withTimeout(
        (async () => {
            const collection = await getTicketLogsCollection();
            return collection.updateOne(
            { tenant_id: tenantId, ticket_id: ticketId },
            {
                $set: { ...latest, status: "pending_review" },
                $setOnInsert: {
                    ticket_id: ticketId,
                    tenant_id: tenantId,
                    created_at: createdAt,
                    admin_notes,
                    customer_contact,
                },
            },
            { upsert: true, maxTimeMS: timeoutMs }
            );
        })(),
        timeoutMs
    );
    if (!result || result.acknowledged !== true) throw new Error("Ticket save was not acknowledged.");
}

module.exports = {
    SAVE_TIMEOUT_MS,
    withTimeout,
    buildEscalationTicket,
    buildEscalationTicketId,
    isEscalation,
    saveEscalationTicket,
};
