/**
 * Chat backend: retrieval + local inference, kept behind a small interface so the route can be
 * tested with a mock and the real implementation can be swapped.
 *
 *   backend.chat(payload, { signal }) -> async iterable of events
 *     { type: "sources", sources: [...] }  { type: "token", text }  { type: "done" }
 *     { type: "error", code, message }
 *
 * The real backend is the Python chat service (src/chat/server.py), which reuses RAGRetriever
 * ($vectorSearch pre-filtered by tenant_id) and the Ollama client. It speaks newline-delimited JSON.
 */
const { getChatConfig } = require("./config");

class ChatBackendError extends Error {
    constructor(message) {
        super(message);
        this.name = "ChatBackendError";
    }
}

function parseLine(line) {
    try {
        const event = JSON.parse(line);
        if (event && typeof event === "object" && typeof event.type === "string") {
            return event;
        }
    } catch {
        // fall through
    }
    throw new ChatBackendError("Chat backend sent a malformed event.");
}

function createHttpChatBackend({ url, token = "", fetchImpl = (...args) => fetch(...args) }) {
    return {
        async *chat(payload, { signal } = {}) {
            let response;
            try {
                response = await fetchImpl(`${url}/v1/chat`, {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        ...(token ? { "X-Chat-Backend-Token": token } : {}),
                    },
                    body: JSON.stringify(payload),
                    signal,
                });
            } catch (error) {
                if (signal && signal.aborted) throw error;
                throw new ChatBackendError("Chat backend is unreachable.");
            }
            if (!response.ok || !response.body) {
                throw new ChatBackendError(`Chat backend returned status ${response.status}.`);
            }

            const decoder = new TextDecoder();
            let buffer = "";
            for await (const chunk of response.body) {
                buffer += decoder.decode(chunk, { stream: true });
                let newline;
                while ((newline = buffer.indexOf("\n")) !== -1) {
                    const line = buffer.slice(0, newline).trim();
                    buffer = buffer.slice(newline + 1);
                    if (line) yield parseLine(line);
                }
            }
            const tail = (buffer + decoder.decode()).trim();
            if (tail) yield parseLine(tail);
        },
    };
}

let backendOverride = null;

/** Test hook: replace the backend (pass null to restore the HTTP backend). */
function setChatBackend(backend) {
    backendOverride = backend;
}

function getChatBackend(env = process.env) {
    if (backendOverride) return backendOverride;
    const config = getChatConfig(env);
    return createHttpChatBackend({ url: config.backendUrl, token: config.backendToken });
}

module.exports = { ChatBackendError, createHttpChatBackend, setChatBackend, getChatBackend };
