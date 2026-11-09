/**
 * Mock Orchestration Gateway implementing chat and contact submission as specified in
 * widget/API_CONTRACT.md. It exists so the widget can be developed and tested without
 * MongoDB, llama.cpp or the real gateway. It performs no retrieval and no generation.
 * Like the real gateway, it sends reply text without document sources or retrieval metadata. Follow-up capability is issued for messages containing "human".
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

    // Demo-only capability store: no visitor data is persisted by this mock.
    const capabilities = new Map();
    app.post("/api/chat/contact", (req, res) => {
        const { tenant_id, session_id, follow_up_token, name, email } = req.body || {};
        const scope = capabilities.get(follow_up_token);
        if (!scope || scope.tenantId !== tenant_id || scope.sessionId !== session_id) {
            return res.status(403).json(errorBody("invalid_follow_up", "Follow-up is unavailable"));
        }
        if (typeof name !== "string" || !name.trim() || name.length > 100 ||
            typeof email !== "string" || email.length > 254 || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
            return res.status(400).json(errorBody("invalid_request", "Name and email are required"));
        }
        return res.json({ status: "saved" });
    });

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

        const answer = lower.includes("human") ? "A staff member will need to help with that request. You can request email follow-up below." : buildAnswer(message);
        let followUp;
        if (lower.includes("human")) {
            const token = crypto.randomUUID();
            capabilities.set(token, { tenantId, sessionId });
            followUp = { available: true, token, contact_email: "support@example.test", contact_phone: "+1 555 123 4567" };
        }
        const wantsStream = String(req.get("accept") || "").includes("text/event-stream");

        if (lower.includes("nostream") || !wantsStream) {
            return res.json({ answer, session_id: sessionId, ...(followUp ? { follow_up: followUp } : {}) });
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
            res.write(sseEvent("done", followUp ? { follow_up: followUp } : {}));
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
