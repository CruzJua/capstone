// Injected as a <style> element inside the widget (and inside the shadow root for the
// <script> embed), so host-page CSS cannot leak in and widget CSS cannot leak out.
export const WIDGET_CSS = `
.cw-root {
    --cw-accent: #1f6feb;
    --cw-accent-text: #ffffff;
    --cw-bg: #ffffff;
    --cw-surface: #f3f4f6;
    --cw-text: #111827;
    --cw-muted: #6b7280;
    --cw-border: #e5e7eb;
    --cw-error: #b91c1c;
    position: fixed;
    bottom: 20px;
    z-index: 2147483000;
    font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
    font-size: 14px;
    line-height: 1.45;
    color: var(--cw-text);
}
.cw-root.cw-right { right: 20px; }
.cw-root.cw-left { left: 20px; }
.cw-root *, .cw-root *::before, .cw-root *::after { box-sizing: border-box; }

@media (prefers-color-scheme: dark) {
    .cw-root {
        --cw-bg: #111827;
        --cw-surface: #1f2937;
        --cw-text: #f9fafb;
        --cw-muted: #9ca3af;
        --cw-border: #374151;
    }
}

.cw-launcher {
    width: 56px;
    height: 56px;
    border: none;
    border-radius: 50%;
    background: var(--cw-accent);
    color: var(--cw-accent-text);
    cursor: pointer;
    box-shadow: 0 4px 14px rgba(0, 0, 0, 0.25);
    display: flex;
    align-items: center;
    justify-content: center;
}
.cw-launcher:focus-visible, .cw-send:focus-visible, .cw-close:focus-visible, .cw-input:focus-visible {
    outline: 2px solid var(--cw-accent);
    outline-offset: 2px;
}

.cw-panel {
    width: 360px;
    max-width: calc(100vw - 24px);
    height: 520px;
    max-height: calc(100vh - 40px);
    background: var(--cw-bg);
    border: 1px solid var(--cw-border);
    border-radius: 14px;
    box-shadow: 0 12px 40px rgba(0, 0, 0, 0.28);
    display: flex;
    flex-direction: column;
    overflow: hidden;
}
.cw-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 14px;
    background: var(--cw-accent);
    color: var(--cw-accent-text);
    font-weight: 600;
}
.cw-close {
    background: transparent;
    border: none;
    color: inherit;
    cursor: pointer;
    font-size: 20px;
    line-height: 1;
    padding: 2px 6px;
}
.cw-messages {
    flex: 1;
    overflow-y: auto;
    padding: 14px;
    display: flex;
    flex-direction: column;
    gap: 10px;
}
.cw-msg {
    max-width: 85%;
    padding: 8px 12px;
    border-radius: 12px;
    white-space: pre-wrap;
    word-wrap: break-word;
}
.cw-msg.cw-user {
    align-self: flex-end;
    background: var(--cw-accent);
    color: var(--cw-accent-text);
    border-bottom-right-radius: 4px;
}
.cw-msg.cw-assistant {
    align-self: flex-start;
    background: var(--cw-surface);
    border-bottom-left-radius: 4px;
}
.cw-msg.cw-error {
    color: var(--cw-error);
    border: 1px solid var(--cw-error);
    background: transparent;
}
.cw-retry {
    margin-top: 6px;
    background: transparent;
    border: 1px solid currentColor;
    color: inherit;
    border-radius: 6px;
    padding: 2px 8px;
    cursor: pointer;
    font-size: 12px;
}
.cw-typing::after {
    content: "\\2026";
    display: inline-block;
    animation: cw-blink 1s steps(3, end) infinite;
}
@keyframes cw-blink { 50% { opacity: 0.25; } }

.cw-form {
    display: flex;
    gap: 8px;
    padding: 10px;
    border-top: 1px solid var(--cw-border);
}
.cw-input {
    flex: 1;
    border: 1px solid var(--cw-border);
    background: var(--cw-bg);
    color: var(--cw-text);
    border-radius: 8px;
    padding: 8px 10px;
    font: inherit;
}
.cw-send {
    border: none;
    border-radius: 8px;
    padding: 0 14px;
    background: var(--cw-accent);
    color: var(--cw-accent-text);
    cursor: pointer;
    font: inherit;
    font-weight: 600;
}
.cw-send:disabled { opacity: 0.5; cursor: not-allowed; }
.cw-footer { padding: 0 10px 8px; font-size: 11px; color: var(--cw-muted); text-align: center; }

@media (prefers-reduced-motion: reduce) {
    .cw-typing::after { animation: none; }
}
`;
