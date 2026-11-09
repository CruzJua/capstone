import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { streamChat, submitContact } from "../lib/chatClient.js";
import { getSessionId, newSessionId } from "../lib/session.js";
import { isRetryable, visitorMessage } from "../lib/messages.js";
import { contactLinks, createConversationScope } from "../lib/followUp.js";
import { WIDGET_CSS } from "../styles.js";

const MAX_MESSAGE_LENGTH = 2000;
const SLOW_REPLY_MS = 6000;

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
    const [slow, setSlow] = useState(false);
    const [messages, setMessages] = useState(() => [
        { id: makeId(), role: "assistant", text: greeting, status: "done" },
    ]);
    const abortRef = useRef(null);
    const scopeRef = useRef(null);
    if (!scopeRef.current) scopeRef.current = createConversationScope();
    const [sessionId, setSessionId] = useState(() => getSessionId(tenantId));
    const [followUp, setFollowUp] = useState(null);
    const [contactName, setContactName] = useState("");
    const [contactEmail, setContactEmail] = useState("");
    const [contactStatus, setContactStatus] = useState("idle");
    const [contactError, setContactError] = useState("");
    const contactPendingRef = useRef(false);
    const sendingRef = useRef(false);
    const listRef = useRef(null);
    const inputRef = useRef(null);
    const lastUserTextRef = useRef("");

    const resetConversation = useCallback((fresh) => {
        scopeRef.current.reset();
        abortRef.current = null;
        sendingRef.current = false;
        contactPendingRef.current = false;
        lastUserTextRef.current = "";
        setSessionId(fresh ? newSessionId(tenantId) : getSessionId(tenantId));
        setMessages([{ id: makeId(), role: "assistant", text: greeting, status: "done" }]);
        setInput("");
        setSending(false);
        setSlow(false);
        setFollowUp(null);
        setContactName("");
        setContactEmail("");
        setContactStatus("idle");
        setContactError("");
        inputRef.current?.focus();
    }, [tenantId, greeting]);

    // Invalidate old callbacks before a changed tenant/API can display their results.
    useLayoutEffect(() => { resetConversation(false); }, [tenantId, apiUrl]);

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

    useEffect(() => () => scopeRef.current.reset(), []);

    const patchMessage = useCallback((id, patch) => {
        setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, ...patch } : m)));
    }, []);

    const send = useCallback(
        async (text) => {
            const trimmed = text.trim().slice(0, MAX_MESSAGE_LENGTH);
            if (!trimmed || sendingRef.current) {
                return;
            }
            sendingRef.current = true;
            lastUserTextRef.current = trimmed;
            const replyId = makeId();
            setMessages((prev) => [
                ...prev,
                { id: makeId(), role: "user", text: trimmed, status: "done" },
                { id: replyId, role: "assistant", text: "", status: "streaming" },
            ]);
            setInput("");
            setSending(true);

            const controller = scopeRef.current.begin();
            abortRef.current = controller;
            let received = "";
            // A local model can take a while to start answering; say so instead of showing dots forever.
            setSlow(false);
            const slowTimer = setTimeout(() => { if (controller.isCurrent()) setSlow(true); }, SLOW_REPLY_MS);

            try {
                const result = await streamChat({
                    apiUrl,
                    tenantId,
                    message: trimmed,
                    sessionId,
                    signal: controller.signal,
                    fetchImpl,
                    onToken: (token) => {
                        if (!controller.isCurrent()) return;
                        clearTimeout(slowTimer);
                        setSlow(false);
                        received += token;
                        patchMessage(replyId, { text: received });
                    },
                });
                if (!controller.isCurrent()) return;
                patchMessage(replyId, { status: "done" });
                if (result.followUp) {
                    setFollowUp(result.followUp);
                    setContactError("");
                }
            } catch (error) {
                if (!controller.isCurrent()) return;
                if (error.code === "aborted") {
                    patchMessage(replyId, { status: "done", text: received || "(stopped)" });
                } else {
                    // Never show the server's own error text: visitors get a fixed, safe message per code.
                    const notice = visitorMessage(error);
                    patchMessage(replyId, {
                        status: "error",
                        retryable: isRetryable(error),
                        text: received ? `${received}\n\n${notice}` : notice,
                    });
                }
            } finally {
                clearTimeout(slowTimer);
                controller.finish();
                if (controller.isCurrent()) {
                    abortRef.current = null;
                    sendingRef.current = false;
                    setSlow(false);
                    setSending(false);
                }
            }
        },
        [apiUrl, tenantId, sessionId, fetchImpl, patchMessage]
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

    const onContactSubmit = async (event) => {
        event.preventDefault();
        if (!followUp || contactPendingRef.current || contactStatus === "saved") return;
        contactPendingRef.current = true;
        const request = scopeRef.current.begin();
        setContactStatus("pending");
        setContactError("");
        const timeout = setTimeout(() => request.abort(), 30000);
        try {
            await submitContact({ apiUrl, tenantId, sessionId, followUpToken: followUp.token,
                name: contactName, email: contactEmail, signal: request.signal, fetchImpl });
            if (request.isCurrent()) {
                setContactStatus("saved");
                setContactName("");
                setContactEmail("");
            }
        } catch {
            if (request.isCurrent()) {
                setContactStatus("error");
                setContactError("Your details could not be saved. Please try again or contact the business directly.");
            }
        } finally {
            clearTimeout(timeout);
            request.finish();
            if (request.isCurrent()) contactPendingRef.current = false;
        }
    };
    const links = contactLinks(followUp);

    const rootStyle = accentColor ? { "--cw-accent": accentColor } : undefined;
    const sideClass = position === "left" ? "cw-left" : "cw-right";

    return (
        <div className={`cw-root ${sideClass}`} style={rootStyle}>
            <style>{WIDGET_CSS}</style>
            {open ? (
                <section className="cw-panel" role="dialog" aria-label={title}>
                    <header className="cw-header">
                        <span>{title}</span>
                        <button type="button" className="cw-new-chat" onClick={() => resetConversation(true)}>
                            New chat
                        </button>
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
                                        <>
                                            <span className="cw-typing" aria-label="Assistant is typing" />
                                            {slow ? (
                                                <span className="cw-slow">Still working on your answer…</span>
                                            ) : null}
                                        </>
                                    ) : null}
                                    {m.status === "error" && m.retryable !== false && isLast && !sending ? (
                                        <div>
                                            <button type="button" className="cw-retry" onClick={retry}>
                                                Retry
                                            </button>
                                        </div>
                                    ) : null}
                                </div>
                            );
                        })}
                        {followUp ? (
                            <section className="cw-follow-up" aria-label="Email follow-up">
                                <strong>Email follow-up</strong>
                                <p>Email follow-up is not immediate. For time-sensitive help, contact the business directly.</p>
                                {links.phone ? <p>Call <a href={links.phone} target="_blank" rel="noopener noreferrer">{followUp.contactPhone}</a></p> : null}
                                {links.email ? <p>Email <a href={links.email} target="_blank" rel="noopener noreferrer">{followUp.contactEmail}</a></p> : null}
                                {contactStatus === "saved" ? (
                                    <p role="status">Your details were saved for the team to review and follow up by email.</p>
                                ) : (
                                    <form className="cw-contact-form" onSubmit={onContactSubmit}>
                                        <p>Leave your name and email to request follow-up about this conversation.</p>
                                        <label>Name<input className="cw-input" name="name" autoComplete="name" required
                                            maxLength={100} value={contactName} disabled={contactStatus === "pending"}
                                            onChange={(e) => setContactName(e.target.value)} /></label>
                                        <label>Email<input className="cw-input" name="email" type="email" autoComplete="email" required
                                            maxLength={254} value={contactEmail} disabled={contactStatus === "pending"}
                                            onChange={(e) => setContactEmail(e.target.value)} /></label>
                                        {contactError ? <p role="alert">{contactError}</p> : null}
                                        <button className="cw-send" type="submit" disabled={contactStatus === "pending" || !contactName.trim() || !contactEmail.trim()}>
                                            {contactStatus === "pending" ? "Saving…" : "Request email follow-up"}
                                        </button>
                                    </form>
                                )}
                            </section>
                        ) : null}
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
