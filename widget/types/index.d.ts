import type { ComponentType } from "react";

export interface ChatWidgetProps {
    /** Base URL of the gateway, e.g. "https://support.example.com". The widget posts to `{apiUrl}/api/chat`. */
    apiUrl: string;
    /** Tenant the visitor is chatting with. */
    tenantId: string;
    title?: string;
    greeting?: string;
    position?: "left" | "right";
    /** Any CSS colour, e.g. "#0b6e4f". */
    accentColor?: string;
    defaultOpen?: boolean;
    /** Override `fetch` (tests, custom auth proxies). */
    fetchImpl?: typeof fetch;
}

export const ChatWidget: ComponentType<ChatWidgetProps>;

export class ChatError extends Error {
    code: string;
    status?: number;
    constructor(code: string, message: string, status?: number);
}

export interface StreamChatOptions {
    apiUrl: string;
    tenantId: string;
    message: string;
    sessionId: string;
    signal?: AbortSignal;
    onToken?: (text: string) => void;
    idleTimeoutMs?: number;
    fetchImpl?: typeof fetch;
}

export interface FollowUp {
    available: true;
    token: string;
    contactEmail?: string;
    contactPhone?: string;
}
export function streamChat(options: StreamChatOptions): Promise<{ answer: string; sessionId: string; followUp?: FollowUp }>;
export interface ContactOptions {
    apiUrl: string;
    tenantId: string;
    sessionId: string;
    followUpToken: string;
    name: string;
    email: string;
    signal?: AbortSignal;
    fetchImpl?: typeof fetch;
}
export function submitContact(options: ContactOptions): Promise<{ status: "saved" }>;

export function getSessionId(tenantId: string, storage?: Pick<Storage, "getItem" | "setItem"> | null): string;

export function newSessionId(tenantId: string, storage?: Pick<Storage, "getItem" | "setItem"> | null): string;
