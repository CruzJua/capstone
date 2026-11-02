"use client";

import React from "react";

export function getScoreBadgeClasses(score) {
    const num = Number(score ?? 0);
    if (num >= 0.75) {
        return "bg-emerald-950/60 border-emerald-800 text-emerald-300";
    }
    if (num >= 0.7) {
        return "bg-amber-950/60 border-amber-800 text-amber-300";
    }
    return "bg-red-950/60 border-red-800 text-red-300";
}

export function getStatusBadge(status) {
    const normalized = (status || "pending_review").toLowerCase();
    if (normalized === "resolved") {
        return {
            label: "resolved",
            classes: "bg-zinc-900 border-emerald-800/80 text-emerald-300",
        };
    }
    if (normalized === "flagged") {
        return {
            label: "flagged",
            classes: "bg-red-950/50 border-red-800 text-red-300",
        };
    }
    return {
        label: "pending_review",
        classes: "bg-amber-950/40 border-amber-800/80 text-amber-300",
    };
}

export function getEscalationBadge(reason) {
    const normalized = (reason || "none").toLowerCase();
    if (normalized === "not_in_docs") {
        return {
            label: "not_in_docs",
            classes: "bg-red-950/40 border-red-800/80 text-red-300",
        };
    }
    if (normalized === "docs_require_human") {
        return {
            label: "docs_require_human",
            classes: "bg-amber-950/40 border-amber-800/80 text-amber-300",
        };
    }
    return {
        label: "none",
        classes: "bg-zinc-900 border-zinc-800 text-zinc-400",
    };
}

export default function TicketTable({
    tickets = [],
    loading = false,
    selectedTicketId = "",
    onSelectTicket,
}) {
    return (
        <section className="rounded border border-zinc-800 bg-zinc-950">
            <div className="border-b border-zinc-800 px-5 py-3 flex items-center justify-between bg-zinc-900/40">
                <div className="flex items-center gap-2.5">
                    <h2 className="text-sm font-semibold text-zinc-100">
                        Interaction Audit Queue
                    </h2>
                    <span className="rounded bg-zinc-900 border border-zinc-800 px-2 py-0.5 font-mono text-xs text-zinc-300">
                        {tickets.length}
                    </span>
                </div>
                <div className="flex items-center gap-3 font-mono text-[11px] text-zinc-500">
                    <span className="text-emerald-400">≥0.75 high</span>
                    <span className="text-amber-400">0.70–0.74 borderline</span>
                    <span className="text-red-400">&lt;0.70 low</span>
                </div>
            </div>

            {loading ? (
                <div className="p-8 text-center font-mono text-xs text-zinc-400">
                    Loading ticket logs from MongoDB Atlas...
                </div>
            ) : tickets.length === 0 ? (
                <div className="p-8 text-center">
                    <p className="text-sm font-medium text-zinc-300">
                        No tickets match the current filter.
                    </p>
                    <p className="font-mono text-xs text-zinc-500 mt-1">
                        Adjust the status filter or search query above.
                    </p>
                </div>
            ) : (
                <div className="overflow-x-auto">
                    <table className="w-full text-left border-collapse">
                        <thead>
                            <tr className="border-b border-zinc-800 bg-zinc-900/20 font-mono text-[11px] uppercase text-zinc-400">
                                <th className="py-2.5 px-5 font-medium">Ticket ID</th>
                                <th className="py-2.5 px-4 font-medium">Date</th>
                                <th className="py-2.5 px-4 font-medium">
                                    Customer Question &amp; Thread
                                </th>
                                <th className="py-2.5 px-4 font-medium">Score</th>
                                <th className="py-2.5 px-4 font-medium">Status</th>
                                <th className="py-2.5 px-5 font-medium text-right">
                                    Action
                                </th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-zinc-800/80 text-xs">
                            {tickets.map((ticket) => {
                                const score = Number(
                                    ticket.similarity_score ?? 0
                                );
                                const scoreClasses = getScoreBadgeClasses(score);
                                const statusBadge = getStatusBadge(ticket.status);
                                const escalationReason =
                                    ticket.escalation_reason || "none";
                                const escalationBadge =
                                    getEscalationBadge(escalationReason);
                                const turnCount = Array.isArray(ticket.messages)
                                    ? ticket.messages.length
                                    : 0;
                                const contactEmail =
                                    ticket.customer_contact?.email || "";
                                const isSelected =
                                    selectedTicketId === ticket.ticket_id;

                                return (
                                    <tr
                                        key={ticket.ticket_id}
                                        onClick={() => onSelectTicket(ticket)}
                                        className={`transition-colors cursor-pointer ${
                                            isSelected
                                                ? "bg-zinc-900/70"
                                                : "hover:bg-zinc-900/35"
                                        }`}
                                    >
                                        <td className="py-3 px-5 font-mono text-xs font-medium text-zinc-100 whitespace-nowrap">
                                            {ticket.ticket_id}
                                        </td>
                                        <td className="py-3 px-4 font-mono text-xs text-zinc-400 whitespace-nowrap">
                                            {ticket.created_at
                                                ? new Date(ticket.created_at)
                                                      .toISOString()
                                                      .slice(0, 16)
                                                      .replace("T", " ")
                                                : "—"}
                                        </td>
                                        <td className="py-3 px-4 text-zinc-200 max-w-md">
                                            <p
                                                className="truncate"
                                                title={ticket.question}
                                            >
                                                {ticket.question}
                                            </p>
                                            <div className="flex flex-wrap items-center gap-1.5 mt-1 font-mono text-[11px] text-zinc-400">
                                                {turnCount > 0 && (
                                                    <span className="rounded bg-zinc-900 border border-zinc-800 px-1.5 py-0.5 text-zinc-300">
                                                        {turnCount} turns
                                                    </span>
                                                )}
                                                {contactEmail ? (
                                                    <span className="rounded bg-zinc-900 border border-zinc-800 px-1.5 py-0.5 text-zinc-300">
                                                        {contactEmail}
                                                    </span>
                                                ) : (
                                                    <span className="text-zinc-500">
                                                        anonymous visitor
                                                    </span>
                                                )}
                                                {escalationReason !== "none" && (
                                                    <span
                                                        className={`rounded border px-1.5 py-0.5 ${escalationBadge.classes}`}
                                                    >
                                                        {escalationBadge.label}
                                                    </span>
                                                )}
                                            </div>
                                        </td>
                                        <td className="py-3 px-4 whitespace-nowrap">
                                            <span
                                                className={`inline-block rounded border px-2 py-0.5 font-mono text-xs ${scoreClasses}`}
                                            >
                                                {score.toFixed(2)}
                                            </span>
                                        </td>
                                        <td className="py-3 px-4 whitespace-nowrap">
                                            <span
                                                className={`inline-block rounded border px-2 py-0.5 font-mono text-xs ${statusBadge.classes}`}
                                            >
                                                {statusBadge.label}
                                            </span>
                                        </td>
                                        <td className="py-3 px-5 text-right whitespace-nowrap">
                                            <button
                                                type="button"
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    onSelectTicket(ticket);
                                                }}
                                                className="rounded border border-zinc-800 bg-zinc-900 hover:bg-zinc-800 px-2.5 py-1 font-mono text-xs text-zinc-200 cursor-pointer"
                                            >
                                                Inspect
                                            </button>
                                        </td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                </div>
            )}
        </section>
    );
}
