"use client";

import React, { useState, useEffect } from "react";
import {
    getScoreBadgeClasses,
    getStatusBadge,
    getEscalationBadge,
} from "./TicketTable";

function renderHighlightedRationale(rationaleText) {
    if (!rationaleText) return null;
    // Highlight bracketed citations like [CARE_GUIDE#1. Vegetable-Tanned Leather Maintenance]
    const parts = String(rationaleText).split(/(\[[^\]]+\])/g);
    return parts.map((part, idx) => {
        if (part.startsWith("[") && part.endsWith("]")) {
            return (
                <span
                    key={idx}
                    className="rounded bg-zinc-800 border border-zinc-700 px-1.5 py-0.5 font-mono text-xs text-zinc-100"
                >
                    {part}
                </span>
            );
        }
        return <React.Fragment key={idx}>{part}</React.Fragment>;
    });
}

function getRoleBadge(role) {
    const normalized = String(role || "customer").toLowerCase();
    if (normalized === "agent" || normalized === "assistant") {
        return {
            label: "agent (Llama-3.2-3B)",
            classes: "bg-zinc-900 border-zinc-700 text-zinc-300",
        };
    }
    return {
        label: "customer",
        classes: "bg-zinc-950 border-zinc-800 text-zinc-200",
    };
}

export default function TicketDetailModal({
    ticket,
    tenantName = "",
    onClose,
    onUpdateTicket,
    updating = false,
}) {
    const [adminNotes, setAdminNotes] = useState("");
    const [copiedEmail, setCopiedEmail] = useState(false);

    useEffect(() => {
        if (!ticket) return;
        let cancelled = false;
        Promise.resolve().then(() => {
            if (!cancelled) {
                setAdminNotes(ticket.admin_notes || "");
                setCopiedEmail(false);
            }
        });
        return () => {
            cancelled = true;
        };
    }, [ticket]);

    if (!ticket) return null;

    const score = Number(ticket.similarity_score ?? 0);
    const scoreClasses = getScoreBadgeClasses(score);
    const statusBadge = getStatusBadge(ticket.status);
    const escalationReason = ticket.escalation_reason || "none";
    const escalationBadge = getEscalationBadge(escalationReason);

    const retrievedChunks = Array.isArray(ticket.retrieved_chunks)
        ? ticket.retrieved_chunks
        : [];
    const messages = Array.isArray(ticket.messages) ? ticket.messages : [];

    const contactName = ticket.customer_contact?.name || "";
    const contactEmail = ticket.customer_contact?.email || "";

    const handleAction = async (nextStatus) => {
        await onUpdateTicket(ticket.ticket_id, {
            status: nextStatus,
            admin_notes: adminNotes,
        });
    };

    const handleCopyEmail = async () => {
        if (!contactEmail) return;
        try {
            await navigator.clipboard.writeText(contactEmail);
            setCopiedEmail(true);
            setTimeout(() => setCopiedEmail(false), 2000);
        } catch {
            // Fallback ignored if clipboard permission denied
        }
    };

    const rawQuestion = (ticket.question || "").trim();
    const businessLabel = (tenantName || ticket.tenant_id || "Customer").trim();

    const mailtoHref = contactEmail.trim()
        ? `mailto:${encodeURIComponent(contactEmail.trim())}?subject=${encodeURIComponent(
              `${businessLabel} Support Follow-Up`
          )}&body=${encodeURIComponent(
              `Hi ${contactName.trim() || "there"},\n\nThanks for reaching out to ${businessLabel}! Following up on your question from our support chat:\n"${rawQuestion}"\n\n[Write response here]\n\n---\nReference ID: ${ticket.ticket_id}\n`
          )}`
        : "";

    return (
        <div
            className="fixed inset-0 z-50 bg-black/75 flex items-center justify-end"
            onClick={onClose}
        >
            <div
                className="h-full w-full max-w-3xl bg-zinc-950 border-l border-zinc-800 flex flex-col"
                onClick={(e) => e.stopPropagation()}
            >
                {/* Drawer Header */}
                <div className="border-b border-zinc-800 px-6 py-4 flex items-center justify-between bg-zinc-900/40">
                    <div>
                        <div className="flex flex-wrap items-center gap-2">
                            <span className="font-mono text-sm font-semibold text-zinc-100">
                                {ticket.ticket_id}
                            </span>
                            <span
                                className={`rounded border px-2 py-0.5 font-mono text-xs ${statusBadge.classes}`}
                            >
                                {statusBadge.label}
                            </span>
                            <span
                                className={`rounded border px-2 py-0.5 font-mono text-xs ${scoreClasses}`}
                            >
                                score: {score.toFixed(2)}
                            </span>
                            {escalationReason !== "none" && (
                                <span
                                    className={`rounded border px-2 py-0.5 font-mono text-xs ${escalationBadge.classes}`}
                                >
                                    escalation: {escalationBadge.label}
                                </span>
                            )}
                        </div>
                        <p className="font-mono text-xs text-zinc-500 mt-1">
                            tenant_id: {ticket.tenant_id} • turns:{" "}
                            {messages.length} • created_at:{" "}
                            {ticket.created_at
                                ? new Date(ticket.created_at).toISOString()
                                : "—"}
                        </p>
                    </div>

                    <button
                        type="button"
                        onClick={onClose}
                        className="rounded border border-zinc-800 bg-zinc-900 hover:bg-zinc-800 px-2.5 py-1 font-mono text-xs text-zinc-400 hover:text-zinc-100 cursor-pointer"
                    >
                        ESC / Close
                    </button>
                </div>

                {/* Drawer Body */}
                <div className="flex-1 overflow-y-auto p-6 space-y-6">
                    {/* 1. Customer Contact & Escalation Handoff Metadata */}
                    <div className="rounded border border-zinc-800 bg-zinc-900/30 p-4 space-y-3">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                            <div>
                                <span className="font-mono text-xs uppercase text-zinc-400 block">
                                    Customer Contact &amp; Escalation Handoff
                                </span>
                                <p className="font-mono text-xs text-zinc-200 mt-1">
                                    {contactName || "Anonymous Visitor"}{" "}
                                    {contactEmail ? (
                                        <span className="text-zinc-400">
                                            &lt;{contactEmail}&gt;
                                        </span>
                                    ) : (
                                        <span className="text-zinc-500">
                                            (no email provided)
                                        </span>
                                    )}
                                </p>
                            </div>

                            {contactEmail ? (
                                <div className="flex items-center gap-2">
                                    <button
                                        type="button"
                                        onClick={handleCopyEmail}
                                        className="rounded border border-zinc-800 bg-zinc-900 hover:bg-zinc-800 px-2.5 py-1 font-mono text-xs text-zinc-300 cursor-pointer"
                                    >
                                        {copiedEmail ? "Copied" : "Copy Email"}
                                    </button>
                                    <a
                                        href={mailtoHref}
                                        target="_blank"
                                        className="rounded border border-zinc-700 bg-zinc-100 hover:bg-white px-3 py-1 font-mono text-xs font-medium text-zinc-900"
                                    >
                                        Draft Email
                                    </a>
                                </div>
                            ) : (
                                <span className="font-mono text-xs text-zinc-500">
                                    no customer email captured
                                </span>
                            )}
                        </div>

                        {ticket.ticket_summary && (
                            <div className="pt-2 border-t border-zinc-800/80">
                                <span className="block font-mono text-[11px] text-zinc-400 mb-1">
                                    ticket_summary (escalation digest)
                                </span>
                                <div className="rounded border border-zinc-800 bg-zinc-950 px-3 py-2 text-xs text-zinc-300 leading-relaxed">
                                    {ticket.ticket_summary}
                                </div>
                            </div>
                        )}
                    </div>

                    {/* 2. Multi-Turn Conversation Transcript */}
                    <div>
                        <div className="flex items-center justify-between mb-2">
                            <span className="font-mono text-xs uppercase text-zinc-400">
                                Full Conversation Transcript (messages[])
                            </span>
                            <span className="font-mono text-xs text-zinc-500">
                                {messages.length} turn(s) logged
                            </span>
                        </div>

                        {messages.length === 0 ? (
                            <div className="rounded border border-zinc-800 bg-zinc-900/40 p-4 text-xs text-zinc-400">
                                Single-turn inquiry:{" "}
                                <span className="text-zinc-200">
                                    {ticket.question}
                                </span>
                            </div>
                        ) : (
                            <div className="rounded border border-zinc-800 bg-zinc-900/20 divide-y divide-zinc-800/80">
                                {messages.map((turn, idx) => {
                                    const roleBadge = getRoleBadge(turn.role);
                                    return (
                                        <div
                                            key={idx}
                                            className="p-3.5 space-y-1.5"
                                        >
                                            <div className="flex items-center justify-between gap-2">
                                                <span
                                                    className={`rounded border px-1.5 py-0.5 font-mono text-[11px] ${roleBadge.classes}`}
                                                >
                                                    #{idx + 1} • {roleBadge.label}
                                                </span>
                                                <span className="font-mono text-[11px] text-zinc-500">
                                                    {turn.timestamp
                                                        ? new Date(
                                                              turn.timestamp
                                                          )
                                                              .toISOString()
                                                              .slice(0, 19)
                                                              .replace("T", " ")
                                                        : ""}
                                                </span>
                                            </div>
                                            <p className="text-xs text-zinc-200 leading-relaxed whitespace-pre-wrap">
                                                {turn.content}
                                            </p>
                                        </div>
                                    );
                                })}
                            </div>
                        )}
                    </div>

                    {/* 3. Evaluated Customer Inquiry & Model Response ([label]) */}
                    <div className="space-y-4">
                        <div>
                            <div className="flex items-center justify-between mb-1.5">
                                <span className="font-mono text-xs uppercase text-zinc-400">
                                    Evaluated Customer Inquiry
                                </span>
                                <span className="font-mono text-xs text-zinc-500">
                                    question
                                </span>
                            </div>
                            <div className="rounded border border-zinc-800 bg-zinc-900/50 p-3.5 text-sm text-zinc-100 leading-relaxed">
                                {ticket.question}
                            </div>
                        </div>

                        <div>
                            <div className="flex items-center justify-between mb-1.5">
                                <span className="font-mono text-xs uppercase text-zinc-400">
                                    Model Response
                                </span>
                                <span className="rounded bg-zinc-900 border border-zinc-800 px-2 py-0.5 font-mono text-xs text-zinc-300">
                                    [label] • Llama-3.2-3B-Instruct
                                </span>
                            </div>
                            <pre className="whitespace-pre-wrap break-words rounded border border-zinc-800 bg-zinc-900 p-4 font-mono text-xs text-zinc-100 leading-relaxed">
                                {ticket.answer}
                            </pre>
                        </div>
                    </div>

                    {/* 4. Model Reasoning ([rationale]) */}
                    <div>
                        <div className="flex items-center justify-between mb-1.5">
                            <span className="font-mono text-xs uppercase text-zinc-400">
                                Model Reasoning
                            </span>
                            <span className="rounded bg-zinc-900 border border-zinc-800 px-2 py-0.5 font-mono text-xs text-zinc-300">
                                [rationale]
                            </span>
                        </div>
                        <div className="rounded border border-zinc-800 bg-zinc-900/40 p-4 font-mono text-xs text-zinc-200 leading-relaxed">
                            {renderHighlightedRationale(ticket.rationale)}
                        </div>
                    </div>

                    {/* 5. Cited Evidence Chunks */}
                    <div>
                        <div className="flex items-center justify-between mb-2">
                            <span className="font-mono text-xs uppercase text-zinc-400">
                                Cited Evidence Chunks ($vectorSearch)
                            </span>
                            <span className="font-mono text-xs text-zinc-500">
                                {retrievedChunks.length} chunk(s) retrieved
                            </span>
                        </div>

                        {retrievedChunks.length === 0 ? (
                            <div className="rounded border border-zinc-800 bg-zinc-900/30 p-4 font-mono text-xs text-zinc-500">
                                No retrieved context chunks recorded.
                            </div>
                        ) : (
                            <div className="space-y-3">
                                {retrievedChunks.map((chunk, idx) => {
                                    const chunkScore = Number(
                                        chunk.score ??
                                            ticket.similarity_score ??
                                            0
                                    );
                                    const chunkBadge =
                                        getScoreBadgeClasses(chunkScore);
                                    return (
                                        <div
                                            key={`${chunk.doc_id}-${idx}`}
                                            className="rounded border border-zinc-800 bg-zinc-900/30 overflow-hidden"
                                        >
                                            <div className="border-b border-zinc-800 px-4 py-2 flex flex-wrap items-center justify-between gap-2 bg-zinc-900/60">
                                                <div className="flex items-center gap-2 font-mono text-xs">
                                                    <span className="text-zinc-100 font-semibold">
                                                        {chunk.doc_id}
                                                    </span>
                                                    <span className="text-zinc-500">
                                                        /
                                                    </span>
                                                    <span className="text-zinc-300">
                                                        {chunk.section ||
                                                            "Overview"}
                                                    </span>
                                                </div>
                                                <span
                                                    className={`rounded border px-1.5 py-0.5 font-mono text-xs ${chunkBadge}`}
                                                >
                                                    cosine:{" "}
                                                    {chunkScore.toFixed(2)}
                                                </span>
                                            </div>
                                            <pre className="whitespace-pre-wrap break-words p-3.5 font-mono text-xs text-zinc-300 leading-relaxed">
                                                {chunk.text}
                                            </pre>
                                        </div>
                                    );
                                })}
                            </div>
                        )}
                    </div>

                    {/* 6. Admin Audit Notes */}
                    <div className="pt-2 border-t border-zinc-800">
                        <label
                            htmlFor="ticket-admin-notes"
                            className="block font-mono text-xs uppercase text-zinc-400 mb-1.5"
                        >
                            Admin Audit Notes
                        </label>
                        <textarea
                            id="ticket-admin-notes"
                            rows={3}
                            value={adminNotes}
                            onChange={(e) => setAdminNotes(e.target.value)}
                            placeholder="Add policy notes, KB gap observations, or record that customer follow-up email was sent..."
                            className="w-full rounded border border-zinc-800 bg-zinc-900 p-3 font-mono text-xs text-zinc-100 focus:border-zinc-600 focus:outline-none"
                        />
                    </div>
                </div>

                {/* Drawer Footer Actions */}
                <div className="border-t border-zinc-800 px-6 py-4 bg-zinc-900/40 flex flex-wrap items-center justify-between gap-3">
                    <span className="font-mono text-xs text-zinc-500">
                        PATCH /api/tickets/{ticket.ticket_id}
                    </span>

                    <div className="flex items-center gap-2.5">
                        <button
                            type="button"
                            disabled={updating}
                            onClick={() => handleAction("flagged")}
                            className="rounded border border-red-800 bg-red-950/60 hover:bg-red-900/60 px-3.5 py-1.5 text-xs font-medium text-red-200 disabled:opacity-50 cursor-pointer transition-colors"
                        >
                            {updating ? "Updating..." : "Flag for Review"}
                        </button>
                        <button
                            type="button"
                            disabled={updating}
                            onClick={() => handleAction("resolved")}
                            className="rounded bg-zinc-100 hover:bg-white px-4 py-1.5 text-xs font-medium text-zinc-900 disabled:opacity-50 cursor-pointer transition-colors"
                        >
                            {updating ? "Saving..." : "Approve Answer"}
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}
