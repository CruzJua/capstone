import { normalizeFollowUp } from "./followUp.js";
import { createSseParser } from "./sse.js";

export class ChatError extends Error {
    constructor(code, message, status, retryAfterSec) {
        super(message);
        this.name = "ChatError";
        this.code = code;
        this.status = status;
        // Seconds from the Retry-After header of a 429, when the gateway sent one.
        this.retryAfterSec = retryAfterSec;
    }
}

export const DEFAULT_IDLE_TIMEOUT_MS = 30000;

function chatUrl(apiUrl) {
    return `${String(apiUrl).replace(/\/+$/, "")}/api/chat`;
}

async function readHttpError(response) {
    let code = `http_${response.status}`;
    let message = `Request failed (${response.status})`;
    try {
        const body = await response.json();
        if (body && body.error) {
            code = body.error.code || code;
            message = body.error.message || message;
        }
    } catch {
        // non-JSON error body
    }
    const retryAfter = Number(response.headers && response.headers.get && response.headers.get("retry-after"));
    return new ChatError(code, message, response.status, Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter : undefined);
}

/**
 * Sends one visitor message to the gateway and streams the reply.
 *
 * Supports the SSE response described in widget/API_CONTRACT.md and falls back to a
 * single JSON body when the gateway (or a buffering proxy) does not stream.
 *
 * Resolves with `{ answer, sessionId, followUp? }`; rejects with `ChatError`
 * (`code === "aborted"` when the caller cancels).
 */
export async function streamChat({
    apiUrl,
    tenantId,
    message,
    sessionId,
    signal,
    onToken = () => {},
    idleTimeoutMs = DEFAULT_IDLE_TIMEOUT_MS,
    fetchImpl = (...args) => fetch(...args),
}) {
    const controller = new AbortController();
    let timedOut = false;
    let timer = null;

    const armTimer = () => {
        if (!idleTimeoutMs) {
            return;
        }
        clearTimeout(timer);
        timer = setTimeout(() => {
            timedOut = true;
            controller.abort();
        }, idleTimeoutMs);
    };

    const onCallerAbort = () => controller.abort();
    if (signal) {
        if (signal.aborted) {
            throw new ChatError("aborted", "Request cancelled");
        }
        signal.addEventListener("abort", onCallerAbort, { once: true });
    }

    const translate = (error) => {
        if (error instanceof ChatError) {
            return error;
        }
        if (timedOut) {
            return new ChatError("timeout", "The assistant took too long to respond");
        }
        if (controller.signal.aborted) {
            return new ChatError("aborted", "Request cancelled");
        }
        return new ChatError("network_error", "Could not reach the support service");
    };

    try {
        armTimer();
        const response = await fetchImpl(chatUrl(apiUrl), {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                Accept: "text/event-stream, application/json",
            },
            body: JSON.stringify({
                tenant_id: tenantId,
                message,
                session_id: sessionId,
            }),
            signal: controller.signal,
        });

        if (!response.ok) {
            throw await readHttpError(response);
        }

        const contentType = response.headers.get("content-type") || "";

        // Non-streaming fallback: one JSON body.
        if (!contentType.includes("text/event-stream") || !response.body) {
            const body = await response.json();
            const answer = String(body.answer ?? "");
            if (answer) {
                onToken(answer);
            }
            const followUp = normalizeFollowUp(body.follow_up);
            return { answer, sessionId: body.session_id ?? sessionId, ...(followUp ? { followUp } : {}) };
        }

        let answer = "";
        let finished = false;
        let followUp;
        let streamError = null;

        const parser = createSseParser(({ event, data }) => {
            let payload = {};
            try {
                payload = data ? JSON.parse(data) : {};
            } catch {
                return; // ignore malformed events rather than failing the whole reply
            }
            if (event === "token") {
                const text = String(payload.text ?? "");
                answer += text;
                onToken(text);
            } else if (event === "error") {
                streamError = new ChatError(
                    payload.code || "stream_error",
                    payload.message || "The assistant ran into a problem"
                );
            } else if (event === "done") {
                finished = true;
                followUp = normalizeFollowUp(payload.follow_up);
            }
        });

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        while (true) {
            const { done, value } = await reader.read();
            if (done) {
                break;
            }
            armTimer();
            parser.push(decoder.decode(value, { stream: true }));
            if (streamError) {
                await reader.cancel().catch(() => {});
                throw streamError;
            }
            if (finished) {
                await reader.cancel().catch(() => {});
                break;
            }
        }
        parser.push(decoder.decode());
        parser.flush();

        if (streamError) {
            throw streamError;
        }
        if (!finished) {
            throw new ChatError("stream_interrupted", "The response ended unexpectedly");
        }
        return { answer, sessionId, ...(followUp ? { followUp } : {}) };
    } catch (error) {
        throw translate(error);
    } finally {
        clearTimeout(timer);
        if (signal) {
            signal.removeEventListener("abort", onCallerAbort);
        }
    }
}

/** Saves visitor contact details; success means persisted, never an email delivery. */
export async function submitContact({ apiUrl, tenantId, sessionId, followUpToken, name, email, signal,
    fetchImpl = (...args) => fetch(...args) }) {
    try {
        if (signal?.aborted) throw new ChatError("aborted", "Request cancelled");
        const response = await fetchImpl(`${chatUrl(apiUrl)}/contact`, {
            method: "POST",
            headers: { "Content-Type": "application/json", Accept: "application/json" },
            body: JSON.stringify({ tenant_id: tenantId, session_id: sessionId,
                follow_up_token: followUpToken, name: name.trim(), email: email.trim() }),
            signal,
        });
        if (!response.ok) throw await readHttpError(response);
        const body = await response.json();
        if (body.status !== "saved") throw new ChatError("invalid_response", "Could not confirm save");
        return { status: "saved" };
    } catch (error) {
        if (signal?.aborted) throw new ChatError("aborted", "Request cancelled");
        if (error instanceof ChatError) throw error;
        throw new ChatError("network_error", "Could not save contact details");
    }
}
