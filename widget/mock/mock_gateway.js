/**
 * Mock Orchestration Gateway implementing ONLY `POST /api/chat` as specified in
 * widget/API_CONTRACT.md. It exists so the widget can be developed and tested without
 * MongoDB, llama.cpp or the real gateway. It performs no retrieval and no generation.
 * Like the real gateway, it sends the visitor only the model's reply: no document sources and no
 * escalation signal (escalations are handled server-side and are invisible to visitors).
 *
 * Run:  npm run mock            (listens on MOCK_PORT, default 4100)
 *
 * Magic words in the visitor message switch behaviors:
 *   "ratelimit" -> HTTP 429 JSON error
 *   "unknown"   -> HTTP 404 (unknown tenant)
 *   "error"     -> SSE stream that fails mid-way with an `error` event
 *   "cutoff"    -> SSE stream that closes without a `done` event
 *   "nostream"  -> single JSON body instead of SSE
 *   "slow"      -> slower token cadence
 */
import { fileURLToPath } from "node:url";
import cors from "cors";
import express from "express";

export const MAX_MESSAGE_LENGTH = 2000;

function errorBody(code, message) {
    return { error: { code, message } };
}

function tokenize(text) {
    return text.match(/\S+\s*/g) || [];
}

function buildAnswer(message) {
    return (
        `This is a mocked answer to: "${message}". ` +
        "Items returned within 30 days are eligible for a full refund."
    );
}

function sseEvent(event, payload) {
    return `event: ${event}\ndata: ${JSON.stringify(payload)}\n\n`;
}

export function createMockApp({ tokenDelayMs = 25 } = {}) {
    const app = express();

    // The real gateway must NOT reuse the admin CORS policy: the widget is embedded on
    // arbitrary storefront origins and sends no cookies (see API_CONTRACT.md).
    app.use(cors({ origin: true, methods: ["POST", "OPTIONS"], allowedHeaders: ["Content-Type"] }));
    app.use(express.json({ limit: "16kb" }));
    app.set("json spaces", 4);

    app.post("/api/chat", (req, res) => {
        const { tenant_id: tenantId, message, session_id: sessionId } = req.body || {};

        if (typeof tenantId !== "string" || !tenantId.trim()) {
            return res.status(400).json(errorBody("invalid_request", "tenant_id is required"));
        }
        if (typeof message !== "string" || !message.trim()) {
            return res.status(400).json(errorBody("invalid_request", "message is required"));
        }
        if (message.length > MAX_MESSAGE_LENGTH) {
            return res
                .status(400)
                .json(errorBody("message_too_long", `message exceeds ${MAX_MESSAGE_LENGTH} characters`));
        }
        if (typeof sessionId !== "string" || !sessionId.trim()) {
            return res.status(400).json(errorBody("invalid_request", "session_id is required"));
        }

        const lower = message.toLowerCase();
        if (lower.includes("ratelimit")) {
            res.set("Retry-After", "30");
            return res.status(429).json(errorBody("rate_limited", "Too many messages. Please wait a moment."));
        }
        if (lower.includes("unknown")) {
            return res.status(404).json(errorBody("unknown_tenant", "No support assistant is configured for this site."));
        }

        const answer = buildAnswer(message);
        const wantsStream = String(req.get("accept") || "").includes("text/event-stream");

        if (lower.includes("nostream") || !wantsStream) {
            return res.json({ answer, session_id: sessionId });
        }

        res.status(200).set({
            "Content-Type": "text/event-stream; charset=utf-8",
            "Cache-Control": "no-cache, no-transform",
            Connection: "keep-alive",
            "X-Accel-Buffering": "no",
        });
        res.flushHeaders();

        const delay = lower.includes("slow") ? tokenDelayMs * 12 : tokenDelayMs;
        const tokens = tokenize(answer);
        const failAt = lower.includes("error") ? Math.floor(tokens.length / 2) : -1;
        const cutAt = lower.includes("cutoff") ? Math.floor(tokens.length / 2) : -1;
        let index = 0;

        const timer = setInterval(() => {
            if (index === failAt) {
                res.write(sseEvent("error", { code: "generation_failed", message: "The assistant ran into a problem." }));
                clearInterval(timer);
                return res.end();
            }
            if (index === cutAt) {
                clearInterval(timer);
                return res.end();
            }
            if (index < tokens.length) {
                res.write(sseEvent("token", { text: tokens[index] }));
                index += 1;
                return;
            }
            res.write(sseEvent("done", {}));
            clearInterval(timer);
            res.end();
        }, delay);

        // Visitor closed the panel / hit Stop: stop generating.
        res.on("close", () => clearInterval(timer));
    });

    return app;
}

const isMain = process.argv[1] === fileURLToPath(import.meta.url);
if (isMain) {
    const port = Number(process.env.MOCK_PORT || 4100);
    createMockApp().listen(port, () => {
        console.log(`Mock gateway (POST /api/chat) listening on http://localhost:${port}`);
    });
}
