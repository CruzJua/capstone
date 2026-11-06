/**
 * POST /api/chat: public, anonymous endpoint used by the embeddable widget.
 * Contract: widget/API_CONTRACT.md.
 *
 * This router is mounted BEFORE the admin CORS / CSRF / requireAuth middleware (see server.js).
 * It therefore does its own: CORS (POST/OPTIONS, Content-Type only, no credentials), per-tenant
 * origin allowlist, rate limiting, body cap and input validation. Visitors never reach MongoDB or
 * the model directly; this route loads the tenant, then hands retrieval and generation to the
 * chat backend, which scopes every $vectorSearch by tenant_id.
 */
const express = require("express");
const { getBusinessesCollection } = require("../db/mongo");
const { getAppMode } = require("../config/mode");
const { isPresetTenantId, isValidTenantId } = require("../config/presets");
const { getChatConfig } = require("../chat/config");
const { resolveAllowedOrigins, isOriginAllowed } = require("../chat/origins");
const { getChatBackend } = require("../chat/backend");
const { buildEscalationTicket, isEscalation, saveEscalationTicket } = require("../chat/escalation");
const { SessionHistory } = require("../chat/sessionHistory");
const { SlidingWindowLimiter } = require("../middleware/rateLimit");

const MAX_MESSAGE_LENGTH = 2000;
const MAX_SOURCES = 20;
const SESSION_ID_PATTERN = /^[A-Za-z0-9_.:-]{16,128}$/;

const ipLimiter = new SlidingWindowLimiter();
const sessionLimiter = new SlidingWindowLimiter();
const sessionHistory = new SessionHistory();

/** Test hook: clears limiter and conversation state. */
function resetChatState() {
    ipLimiter.reset();
    sessionLimiter.reset();
    sessionHistory.reset();
}

function sendError(res, status, code, message) {
    return res.status(status).json({ error: { code, message } });
}

function applyCorsHeaders(req, res, next) {
    // No credentials are ever allowed. The Origin is echoed so the widget can read error bodies,
    // including a 403 origin_not_allowed; the per-tenant allowlist is enforced on the POST itself
    // because a preflight carries no tenant_id.
    const origin = req.headers.origin;
    if (origin) {
        res.setHeader("Access-Control-Allow-Origin", origin);
    }
    res.append("Vary", "Origin");
    res.setHeader("X-Content-Type-Options", "nosniff");
    res.setHeader("Cache-Control", "no-store");
    next();
}

function handlePreflight(req, res) {
    res.setHeader("Access-Control-Allow-Methods", "POST, OPTIONS");
    res.setHeader("Access-Control-Allow-Headers", "Content-Type");
    res.setHeader("Access-Control-Max-Age", "600");
    return res.status(204).end();
}

function clientIp(req) {
    return req.ip || (req.socket && req.socket.remoteAddress) || "unknown";
}

function rateLimited(res, retryAfterSec) {
    res.setHeader("Retry-After", String(retryAfterSec));
    return sendError(res, 429, "rate_limited", "Too many messages. Please wait a moment.");
}

function limitByIp(req, res, next) {
    const config = getChatConfig(process.env);
    const result = ipLimiter.hit(`ip:${clientIp(req)}`, config.rateLimitPerIp, config.rateLimitWindowMs);
    if (!result.allowed) return rateLimited(res, result.retryAfterSec);
    return next();
}

function numberOr(value, fallback, min, max) {
    const number = Number(value);
    if (value === undefined || value === null || Number.isNaN(number)) return fallback;
    return Math.min(max, Math.max(min, number));
}

/** Normalizes businesses.agent_config for the backend; missing values take the documented defaults. */
function buildAgentConfig(raw) {
    const config = raw && typeof raw === "object" && !Array.isArray(raw) ? raw : {};
    const text = (value, max) => (typeof value === "string" ? value.trim().slice(0, max) : "");
    return {
        system_prompt: text(config.system_prompt, 4000),
        agent_tone: text(config.agent_tone, 200),
        temperature: numberOr(config.temperature, 0.2, 0, 1),
        max_context_chunks: Math.round(numberOr(config.max_context_chunks, 4, 1, 8)),
        similarity_threshold: numberOr(config.similarity_threshold, 0.7, 0, 1),
    };
}

/**
 * Loads a tenant the same way the admin API scopes them: standard mode never serves the preset
 * (synthetic training) tenants, preset_training mode serves only them.
 */
async function loadTenant(tenantId) {
    if (!isValidTenantId(tenantId)) return null;
    const presetOnly = getAppMode(process.env) === "preset_training";
    if (isPresetTenantId(tenantId) !== presetOnly) return null;
    const businesses = await getBusinessesCollection();
    return businesses.findOne(
        { tenant_id: tenantId },
        { projection: { _id: 0, tenant_id: 1, agent_config: 1, widget_config: 1 } }
    );
}

/**
 * Retrieval details are never sent to the visitor. They are kept only to fill the human-review ticket
 * when the model escalates, and even there only as doc_id, section and score: never chunk text or
 * embeddings.
 */
function sanitizeSources(sources) {
    if (!Array.isArray(sources)) return [];
    return sources
        .filter((source) => source && typeof source === "object")
        .slice(0, MAX_SOURCES)
        .map((source) => ({
            doc_id: String(source.doc_id ?? "unknown"),
            section: String(source.section ?? ""),
            score: typeof source.score === "number" && Number.isFinite(source.score) ? source.score : 0,
        }));
}

const UNAVAILABLE_MESSAGE = "The support assistant is temporarily unavailable. Please try again shortly.";
const GENERATION_FAILED_MESSAGE = "The assistant ran into a problem.";

const ESCALATED_WITHOUT_REPLY = "(The assistant escalated without a reply.)";

/**
 * Remembers a finished exchange for follow-up questions and, when the model escalated it, saves the
 * conversation as a human-review ticket. Escalation is invisible to the visitor, and a failure to save
 * the ticket is logged (name of the error only) but never affects the reply they already received.
 */
async function recordTurn({ tenantId, sessionId, message, answer, done, sources, historyMaxMessages }) {
    const escalated = isEscalation(done);
    const text = answer.trim() ? answer : escalated ? ESCALATED_WITHOUT_REPLY : "";
    if (!text) return;
    sessionHistory.add(tenantId, sessionId, message, text, historyMaxMessages);
    if (!escalated) return;
    try {
        const ticket = buildEscalationTicket({
            tenantId,
            sessionId,
            message,
            answer: text,
            done,
            sources,
            transcript: sessionHistory.getTranscript(tenantId, sessionId),
        });
        await saveEscalationTicket(ticket);
        // Ids only: never the conversation text.
        console.log(`[POST /api/chat] Escalation ticket saved: ${ticket.ticket_id} (tenant ${tenantId})`);
    } catch (error) {
        console.error("[POST /api/chat] Could not save escalation ticket:", error && error.name);
    }
}

/**
 * Drives the backend iterator. Returns { completed, timedOut } and reports through `sink`.
 * `first` is the already-pulled first iterator result (used to decide HTTP status before streaming).
 */
async function consumeEvents(iterator, first, sink, isGone) {
    let current = first;
    while (true) {
        if (isGone()) return { completed: false };
        if (current.done) {
            sink.onError("generation_failed", GENERATION_FAILED_MESSAGE);
            return { completed: false };
        }
        const event = current.value || {};
        if (event.type === "sources") {
            sink.onSources(sanitizeSources(event.sources));
        } else if (event.type === "token" && typeof event.text === "string") {
            sink.onToken(event.text);
        } else if (event.type === "done") {
            sink.onDone(event);
            return { completed: true };
        } else if (event.type === "error") {
            sink.onError("generation_failed", GENERATION_FAILED_MESSAGE);
            return { completed: false };
        }
        current = await iterator.next();
    }
}

async function handleChat(req, res) {
    const body = req.body;
    if (!body || typeof body !== "object" || Array.isArray(body)) {
        return sendError(res, 400, "invalid_request", "Request body must be a JSON object.");
    }
    const { tenant_id: rawTenantId, message: rawMessage, session_id: sessionId } = body;

    // Only plain strings are accepted, so a tenant_id such as {"$ne": null} can never reach a query.
    if (typeof rawTenantId !== "string" || !rawTenantId.trim()) {
        return sendError(res, 400, "invalid_request", "tenant_id is required");
    }
    if (typeof rawMessage !== "string" || !rawMessage.trim()) {
        return sendError(res, 400, "invalid_request", "message is required");
    }
    if (rawMessage.length > MAX_MESSAGE_LENGTH) {
        return sendError(res, 400, "message_too_long", `message exceeds ${MAX_MESSAGE_LENGTH} characters`);
    }
    if (typeof sessionId !== "string" || !SESSION_ID_PATTERN.test(sessionId)) {
        return sendError(
            res,
            400,
            "invalid_request",
            "session_id is required (16-128 characters: letters, digits, '_', '-', '.', ':')"
        );
    }

    const config = getChatConfig(process.env);
    const tenantId = rawTenantId.trim();
    const message = rawMessage.trim();

    const sessionResult = sessionLimiter.hit(
        `session:${tenantId}:${sessionId}`,
        config.rateLimitPerSession,
        config.rateLimitWindowMs
    );
    if (!sessionResult.allowed) return rateLimited(res, sessionResult.retryAfterSec);

    let tenant;
    try {
        tenant = await loadTenant(tenantId);
    } catch (error) {
        console.error("[POST /api/chat] Tenant lookup failed:", error.name);
        return sendError(res, 503, "service_unavailable", UNAVAILABLE_MESSAGE);
    }
    if (!tenant) {
        return sendError(res, 404, "unknown_tenant", "No support assistant is configured for this site.");
    }

    const allowedOrigins = resolveAllowedOrigins(tenant, config.defaultAllowedOrigins);
    if (!isOriginAllowed(req.headers.origin, allowedOrigins)) {
        return sendError(res, 403, "origin_not_allowed", "This site is not allowed to use this support assistant.");
    }

    const wantsStream = String(req.get("accept") || "").includes("text/event-stream");
    const payload = {
        tenant_id: tenant.tenant_id,
        query: message,
        history: sessionHistory.get(tenant.tenant_id, sessionId),
        agent_config: buildAgentConfig(tenant.agent_config),
    };

    // Abort generation as soon as the visitor goes away or the overall deadline passes.
    const controller = new AbortController();
    let finished = false;
    let timedOut = false;
    res.on("close", () => {
        if (!finished) controller.abort();
    });
    const deadline = setTimeout(() => {
        timedOut = true;
        controller.abort();
    }, config.maxDurationMs);
    const isGone = () => controller.signal.aborted && !timedOut;
    // A stream that ends or fails because the deadline passed is reported as a timeout.
    const failure = (code, text) =>
        timedOut ? { code: "timeout", message: "The assistant took too long to respond." } : { code, message: text };

    let iterator = null;
    let heartbeat = null;
    const cleanup = async () => {
        clearTimeout(deadline);
        if (heartbeat) clearInterval(heartbeat);
        finished = true;
        if (iterator && typeof iterator.return === "function") {
            try {
                await iterator.return();
            } catch {
                // the backend stream is already closed
            }
        }
    };

    try {
        let first;
        try {
            iterator = getChatBackend(process.env).chat(payload, { signal: controller.signal })[Symbol.asyncIterator]();
            first = await iterator.next();
        } catch (error) {
            if (isGone()) return undefined;
            console.error("[POST /api/chat] Backend unavailable:", error.name);
            return sendError(res, 503, "service_unavailable", UNAVAILABLE_MESSAGE);
        }
        if (isGone()) return undefined;
        if (first.done || (first.value && first.value.type === "error")) {
            // Nothing has been streamed yet, so a real HTTP status can still be returned.
            return sendError(res, 503, "service_unavailable", UNAVAILABLE_MESSAGE);
        }

        let answer = "";
        let outcome;
        // Retrieval details and the model's action are kept server-side. They are never sent to the
        // visitor; they only feed the human-review ticket when the model escalates.
        let sources = [];
        let doneEvent = null;
        const turn = () => ({
            tenantId: tenant.tenant_id,
            sessionId,
            message,
            answer,
            done: doneEvent,
            sources,
            historyMaxMessages: config.historyMaxMessages,
        });

        if (!wantsStream) {
            let errorEvent = null;
            outcome = await consumeEvents(
                iterator,
                first,
                {
                    onSources: (items) => {
                        sources = items;
                    },
                    onToken: (text) => {
                        answer += text;
                    },
                    onDone: (event) => {
                        doneEvent = event;
                    },
                    onError: (code, text) => {
                        errorEvent = { code, text };
                    },
                },
                isGone
            ).catch((error) => {
                if (!isGone()) console.error("[POST /api/chat] Generation failed:", error.name);
                errorEvent = timedOut
                    ? { code: "timeout", text: "The assistant took too long to respond." }
                    : { code: "generation_failed", text: GENERATION_FAILED_MESSAGE };
                return { completed: false };
            });
            if (isGone()) return undefined;
            if (errorEvent || !outcome.completed) {
                return sendError(res, 503, "service_unavailable", UNAVAILABLE_MESSAGE);
            }
            await recordTurn(turn());
            return res.json({ answer, session_id: sessionId });
        }

        res.status(200);
        res.set({
            "Content-Type": "text/event-stream; charset=utf-8",
            "Cache-Control": "no-cache, no-transform",
            Connection: "keep-alive",
            "X-Accel-Buffering": "no",
        });
        res.flushHeaders();
        if (res.socket && typeof res.socket.setNoDelay === "function") res.socket.setNoDelay(true);

        const write = (chunk) => {
            if (!res.writableEnded && !res.destroyed) res.write(chunk);
        };
        const sendEvent = (name, data) => write(`event: ${name}\ndata: ${JSON.stringify(data)}\n\n`);
        // Keeps proxies and the widget's idle timer alive while a slow local model reads the prompt.
        heartbeat = setInterval(() => write(": ping\n\n"), config.heartbeatMs);
        if (typeof heartbeat.unref === "function") heartbeat.unref();

        try {
            outcome = await consumeEvents(
                iterator,
                first,
                {
                    onSources: (items) => {
                        sources = items;
                    },
                    onToken: (text) => {
                        answer += text;
                        sendEvent("token", { text });
                    },
                    onDone: (event) => {
                        doneEvent = event;
                        sendEvent("done", {});
                    },
                    onError: (code, text) => sendEvent("error", failure(code, text)),
                },
                isGone
            );
        } catch (error) {
            if (!isGone()) {
                console.error("[POST /api/chat] Generation failed:", error.name);
                sendEvent("error", failure("generation_failed", GENERATION_FAILED_MESSAGE));
            }
            outcome = { completed: false };
        }
        // `done` has already been sent, so saving an escalation ticket never delays the visitor.
        if (outcome.completed) await recordTurn(turn());
        finished = true;
        if (!res.writableEnded) res.end();
        return undefined;
    } finally {
        await cleanup();
    }
}

const router = express.Router();
router.use(applyCorsHeaders);
router.options("/", handlePreflight);
router.post("/", limitByIp, express.json({ limit: "16kb" }), (req, res, next) => {
    handleChat(req, res).catch(next);
});
router.all("/", (req, res) => {
    res.setHeader("Allow", "POST, OPTIONS");
    return sendError(res, 405, "method_not_allowed", "Use POST /api/chat.");
});
router.use((req, res) => sendError(res, 404, "not_found", "Not found."));
// eslint-disable-next-line no-unused-vars
router.use((error, req, res, next) => {
    if (res.headersSent) {
        return res.end();
    }
    if (error && (error.type === "entity.parse.failed" || error.type === "entity.too.large")) {
        return sendError(res, 400, "invalid_request", "Request body is not valid JSON or is too large.");
    }
    console.error("[POST /api/chat] Unexpected error:", error && error.name);
    return sendError(res, 500, "internal_error", "Something went wrong.");
});

module.exports = { router, resetChatState, buildAgentConfig, MAX_MESSAGE_LENGTH };
