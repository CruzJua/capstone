import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { streamChat } from "../lib/chatClient.js";
import { getSessionId } from "../lib/session.js";
import { WIDGET_CSS } from "../styles.js";

const MAX_MESSAGE_LENGTH = 2000;

let nextId = 0;
function makeId() {
    nextId += 1;
    return `m${nextId}`;
}

/**
 * Embeddable support chat. Talks ONLY to the Orchestration Gateway (`POST {apiUrl}/api/chat`);
 * it never touches the database and holds no secrets. All message text is rendered as plain
 * text (React escapes it), never as HTML.
 */
export default function ChatWidget({
    apiUrl,
    tenantId,
    title = "Support",
    greeting = "Hi! How can I help you today?",
    position = "right",
    accentColor,
    defaultOpen = false,
    fetchImpl,
}) {
    const [open, setOpen] = useState(defaultOpen);
    const [input, setInput] = useState("");
    const [sending, setSending] = useState(false);
    const [messages, setMessages] = useState(() => [
        { id: makeId(), role: "assistant", text: greeting, status: "done" },
    ]);
    const abortRef = useRef(null);
    const listRef = useRef(null);
    const inputRef = useRef(null);
    const lastUserTextRef = useRef("");

    const sessionId = useMemo(() => getSessionId(tenantId), [tenantId]);

    useEffect(() => {
        const el = listRef.current;
        if (el) {
            el.scrollTop = el.scrollHeight;
        }
    }, [messages, open]);

    useEffect(() => {
        if (open && inputRef.current) {
            inputRef.current.focus();
        }
    }, [open]);

    useEffect(() => () => abortRef.current?.abort(), []);

    const patchMessage = useCallback((id, patch) => {
        setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, ...patch } : m)));
    }, []);

    const send = useCallback(
        async (text) => {
            const trimmed = text.trim().slice(0, MAX_MESSAGE_LENGTH);
            if (!trimmed || sending) {
                return;
            }
            lastUserTextRef.current = trimmed;
            const replyId = makeId();
            setMessages((prev) => [
                ...prev,
                { id: makeId(), role: "user", text: trimmed, status: "done" },
                { id: replyId, role: "assistant", text: "", status: "streaming" },
            ]);
            setInput("");
            setSending(true);

            const controller = new AbortController();
            abortRef.current = controller;
            let received = "";

            try {
                await streamChat({
                    apiUrl,
                    tenantId,
                    message: trimmed,
                    sessionId,
                    signal: controller.signal,
                    fetchImpl,
                    onToken: (token) => {
                        received += token;
                        patchMessage(replyId, { text: received });
                    },
                });
                patchMessage(replyId, { status: "done" });
            } catch (error) {
                if (error.code === "aborted") {
                    patchMessage(replyId, { status: "done", text: received || "(stopped)" });
                } else {
                    patchMessage(replyId, {
                        status: "error",
                        text: received
                            ? `${received}\n\n${error.message}`
                            : error.message || "Something went wrong.",
                    });
                }
            } finally {
                abortRef.current = null;
                setSending(false);
            }
        },
        [apiUrl, tenantId, sessionId, sending, fetchImpl, patchMessage]
    );

    const retry = useCallback(() => {
        const text = lastUserTextRef.current;
        if (!text) {
            return;
        }
        // Drop the failed exchange (user message + error reply) before resending.
        setMessages((prev) => prev.slice(0, -2));
        send(text);
    }, [send]);

    const onSubmit = (event) => {
        event.preventDefault();
        send(input);
    };

    const rootStyle = accentColor ? { "--cw-accent": accentColor } : undefined;
    const sideClass = position === "left" ? "cw-left" : "cw-right";

    return (
        <div className={`cw-root ${sideClass}`} style={rootStyle}>
            <style>{WIDGET_CSS}</style>
            {open ? (
                <section className="cw-panel" role="dialog" aria-label={title}>
                    <header className="cw-header">
                        <span>{title}</span>
                        <button
                            type="button"
                            className="cw-close"
                            aria-label="Close chat"
                            onClick={() => setOpen(false)}
                        >
                            ×
                        </button>
                    </header>
                    <div className="cw-messages" ref={listRef} role="log" aria-live="polite">
                        {messages.map((m, index) => {
                            const isLast = index === messages.length - 1;
                            return (
                                <div
                                    key={m.id}
                                    className={`cw-msg cw-${m.role}${m.status === "error" ? " cw-error" : ""}`}
                                >
                                    {m.text}
                                    {m.status === "streaming" && !m.text ? (
                                        <span className="cw-typing" aria-label="Assistant is typing" />
                                    ) : null}
                                    {m.status === "error" && isLast && !sending ? (
                                        <div>
                                            <button type="button" className="cw-retry" onClick={retry}>
                                                Retry
                                            </button>
                                        </div>
                                    ) : null}
                                </div>
                            );
                        })}
                    </div>
                    <form className="cw-form" onSubmit={onSubmit}>
                        <input
                            ref={inputRef}
                            className="cw-input"
                            value={input}
                            maxLength={MAX_MESSAGE_LENGTH}
                            placeholder="Type your question…"
                            aria-label="Your message"
                            onChange={(e) => setInput(e.target.value)}
                        />
                        {sending ? (
                            <button
                                type="button"
                                className="cw-send"
                                onClick={() => abortRef.current?.abort()}
                            >
                                Stop
                            </button>
                        ) : (
                            <button type="submit" className="cw-send" disabled={!input.trim()}>
                                Send
                            </button>
                        )}
                    </form>
                    <div className="cw-footer">AI assistant – answers may contain mistakes.</div>
                </section>
            ) : (
                <button
                    type="button"
                    className="cw-launcher"
                    aria-label={`Open ${title} chat`}
                    onClick={() => setOpen(true)}
                >
                    <svg width="26" height="26" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                        <path d="M4 3h16a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H9l-5 4v-4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z" />
                    </svg>
                </button>
            )}
        </div>
    );
}
