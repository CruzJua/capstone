"use client";

import React, { useState, useEffect, useCallback, useMemo } from "react";
import Link from "next/link";
import { useTenant } from "@/context/TenantContext";
import { fetchTenantTickets, updateTicketStatus } from "@/lib/api";
import MetricCard from "@/components/MetricCard";
import TicketTable from "@/components/TicketTable";
import TicketDetailModal from "@/components/TicketDetailModal";

const STATUS_FILTERS = [
    { key: "all", label: "All" },
    { key: "resolved", label: "Resolved" },
    { key: "pending_review", label: "Pending Review" },
    { key: "flagged", label: "Flagged" },
];

export default function TicketsPage() {
    const {
        activeTenant,
        activeTenantId,
        loading: tenantsLoading,
    } = useTenant();

    const [allTickets, setAllTickets] = useState([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    const [statusFilter, setStatusFilter] = useState("all");
    const [searchQuery, setSearchQuery] = useState("");
    const [selectedTicketId, setSelectedTicketId] = useState("");
    const [updatingTicket, setUpdatingTicket] = useState(false);
    const [toast, setToast] = useState(null);

    const showToast = useCallback((type, title, message) => {
        setToast({ type, title, message, id: Date.now() });
    }, []);

    useEffect(() => {
        if (!toast) return;
        const timer = setTimeout(() => setToast(null), 4000);
        return () => clearTimeout(timer);
    }, [toast]);

    const loadTickets = useCallback(async (tenantId) => {
        if (!tenantId) return;
        setLoading(true);
        setError(null);
        try {
            const list = await fetchTenantTickets(tenantId, { status: "all" });
            setAllTickets(list);
        } catch (err) {
            setError(
                err.message || "Failed to load tickets from Orchestration Gateway."
            );
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        if (!activeTenantId) return;
        let cancelled = false;

        async function initTenantTickets() {
            await Promise.resolve();
            if (cancelled) return;
            setStatusFilter("all");
            setSearchQuery("");
            setSelectedTicketId("");
            setLoading(true);
            setError(null);

            try {
                const list = await fetchTenantTickets(activeTenantId, {
                    status: "all",
                });
                if (!cancelled) {
                    setAllTickets(list);
                }
            } catch (err) {
                if (!cancelled) {
                    setError(
                        err.message ||
                            "Failed to load tickets from Orchestration Gateway."
                    );
                }
            } finally {
                if (!cancelled) {
                    setLoading(false);
                }
            }
        }

        initTenantTickets();
        return () => {
            cancelled = true;
        };
    }, [activeTenantId]);

    const handleUpdateTicket = useCallback(
        async (ticketId, payload) => {
            setUpdatingTicket(true);
            try {
                const updated = await updateTicketStatus(ticketId, payload);

                setAllTickets((prev) =>
                    prev.map((item) =>
                        item.ticket_id === ticketId ? updated : item
                    )
                );

                showToast(
                    "success",
                    "Ticket Updated in MongoDB Atlas",
                    `${ticketId} marked as '${updated.status}'.`
                );
            } catch (err) {
                showToast(
                    "error",
                    "Failed to Update Ticket",
                    err.message || "Could not update ticket status."
                );
            } finally {
                setUpdatingTicket(false);
            }
        },
        [showToast]
    );

    const filteredTickets = useMemo(() => {
        return allTickets.filter((ticket) => {
            if (statusFilter !== "all" && ticket.status !== statusFilter) {
                return false;
            }
            if (searchQuery.trim()) {
                const q = searchQuery.trim().toLowerCase();
                const inId = (ticket.ticket_id || "").toLowerCase().includes(q);
                const inQuestion = (ticket.question || "")
                    .toLowerCase()
                    .includes(q);
                const inAnswer = (ticket.answer || "")
                    .toLowerCase()
                    .includes(q);
                const inRationale = (ticket.rationale || "")
                    .toLowerCase()
                    .includes(q);
                const inSummary = (ticket.ticket_summary || "")
                    .toLowerCase()
                    .includes(q);
                const inContact =
                    (ticket.customer_contact?.email || "")
                        .toLowerCase()
                        .includes(q) ||
                    (ticket.customer_contact?.name || "")
                        .toLowerCase()
                        .includes(q);
                const inMessages = Array.isArray(ticket.messages)
                    ? ticket.messages.some((m) =>
                            (m.content || "").toLowerCase().includes(q)
                        )
                    : false;
                return (
                    inId ||
                    inQuestion ||
                    inAnswer ||
                    inRationale ||
                    inSummary ||
                    inContact ||
                    inMessages
                );
            }
            return true;
        });
    }, [allTickets, statusFilter, searchQuery]);

    const totalInquiries = allTickets.length;
    const resolvedCount = allTickets.filter(
        (t) => t.status === "resolved"
    ).length;
    const pendingCount = allTickets.filter(
        (t) => t.status === "pending_review"
    ).length;
    const flaggedCount = allTickets.filter(
        (t) => t.status === "flagged"
    ).length;
    const resolutionRate =
        totalInquiries > 0
            ? `${Math.round((resolvedCount / totalInquiries) * 100)}%`
            : "0%";

    const activeTicket =
        allTickets.find((t) => t.ticket_id === selectedTicketId) || null;

    return (
        <div className="min-h-full bg-zinc-950 text-zinc-100">
            {/* Notification Toast */}
            {toast && (
                <div
                    role="status"
                    aria-live="polite"
                    className="fixed bottom-5 right-5 z-50 max-w-md"
                >
                    <div
                        className={`rounded border p-3.5 text-sm ${
                            toast.type === "error"
                                ? "bg-red-950 border-red-800 text-red-100"
                                : "bg-zinc-900 border-emerald-700 text-zinc-100"
                        }`}
                    >
                        <p className="font-mono text-xs uppercase tracking-wide font-semibold">
                            {toast.title}
                        </p>
                        <p className="text-xs text-zinc-300 mt-1">
                            {toast.message}
                        </p>
                    </div>
                </div>
            )}

            {/* Page Header */}
            <header className="bg-zinc-950 border-b border-zinc-800 px-6 py-4">
                <div className="max-w-6xl mx-auto flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
                    <div>
                        <div className="flex items-center gap-2.5">
                            <h1 className="text-lg font-semibold text-zinc-100">
                                {tenantsLoading
                                    ? "Loading Ticket Review Queue..."
                                    : "Ticket Review Queue"}
                            </h1>
                            {activeTenantId && (
                                <span className="rounded bg-zinc-900 border border-zinc-800 px-2 py-0.5 font-mono text-xs text-zinc-300">
                                    {activeTenantId}
                                </span>
                            )}
                        </div>
                        <p className="text-xs text-zinc-400 mt-1">
                            Audit customer inquiries, model reasoning, and{" "}
                            <code className="font-mono">$vectorSearch</code> evidence for{" "}
                            <span className="text-zinc-200 font-medium">
                                {activeTenant?.name || activeTenantId || "active tenant"}
                            </span>
                            .
                        </p>
                    </div>

                    <div className="flex items-center gap-2">
                        <button
                            type="button"
                            onClick={() => loadTickets(activeTenantId)}
                            disabled={loading || !activeTenantId}
                            className="rounded border border-zinc-800 bg-zinc-900 hover:bg-zinc-800 px-3 py-1.5 font-mono text-xs text-zinc-200 disabled:opacity-50 cursor-pointer"
                        >
                            Refresh
                        </button>
                        <Link
                            href="/profile"
                            className="rounded border border-zinc-800 bg-zinc-900 hover:bg-zinc-800 px-3 py-1.5 text-xs font-medium text-zinc-200"
                        >
                            Runtime Thresholds
                        </Link>
                    </div>
                </div>
            </header>

            <main className="max-w-6xl mx-auto px-6 py-6 space-y-6">
                {error && (
                    <div className="rounded border border-red-900 bg-red-950/50 p-4 flex items-center justify-between gap-4 text-red-200">
                        <div className="text-xs">
                            <p className="font-semibold">Failed to load ticket logs</p>
                            <p className="font-mono text-red-300 mt-0.5">{error}</p>
                        </div>
                        <button
                            type="button"
                            onClick={() => loadTickets(activeTenantId)}
                            className="rounded border border-red-800 bg-red-900 px-3 py-1 text-xs font-medium text-white hover:bg-red-800 cursor-pointer"
                        >
                            Retry
                        </button>
                    </div>
                )}

                {/* Key Indicators */}
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                    <MetricCard
                        label="Total Inquiries"
                        value={totalInquiries}
                        badge="ticket_logs"
                        subtext={`tenant_id: ${activeTenantId || "—"}`}
                    />
                    <MetricCard
                        label="Resolution Rate"
                        value={resolutionRate}
                        badge={`${resolvedCount}/${totalInquiries} resolved`}
                        subtext="human-verified grounded responses"
                    />
                    <MetricCard
                        label="Pending Reviews"
                        value={pendingCount}
                        badge={`${flaggedCount} flagged`}
                        subtext="awaiting administrator audit"
                    />
                </div>

                {/* Filter Bar & Keyword Search */}
                <div className="rounded border border-zinc-800 bg-zinc-900/40 p-3.5 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                    <div className="flex flex-wrap items-center gap-1.5">
                        {STATUS_FILTERS.map((item) => {
                            const active = statusFilter === item.key;
                            const count =
                                item.key === "all"
                                    ? totalInquiries
                                    : item.key === "resolved"
                                    ? resolvedCount
                                    : item.key === "pending_review"
                                    ? pendingCount
                                    : flaggedCount;

                            return (
                                <button
                                    key={item.key}
                                    type="button"
                                    onClick={() => setStatusFilter(item.key)}
                                    className={`rounded px-3 py-1.5 text-xs font-medium transition-colors cursor-pointer border ${
                                        active
                                            ? "bg-zinc-100 text-zinc-900 border-zinc-100"
                                            : "bg-zinc-900 text-zinc-300 border-zinc-800 hover:border-zinc-700"
                                    }`}
                                >
                                    {item.label}{" "}
                                    <span
                                        className={`ml-1 font-mono text-[11px] ${
                                            active
                                                ? "text-zinc-700"
                                                : "text-zinc-500"
                                        }`}
                                    >
                                        ({count})
                                    </span>
                                </button>
                            );
                        })}
                    </div>

                    <div className="flex items-center gap-2">
                        <input
                            type="text"
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                            placeholder="Search customer inquiries or ticket ID..."
                            className="w-full sm:w-72 bg-zinc-900 border border-zinc-800 rounded px-3 py-1.5 text-xs text-zinc-100 focus:border-zinc-600 focus:outline-none"
                        />
                        {searchQuery && (
                            <button
                                type="button"
                                onClick={() => setSearchQuery("")}
                                className="rounded border border-zinc-800 bg-zinc-900 px-2 py-1.5 font-mono text-xs text-zinc-400 hover:text-zinc-200 cursor-pointer"
                            >
                                Clear
                            </button>
                        )}
                    </div>
                </div>

                {/* Ticket Table */}
                <TicketTable
                    tickets={filteredTickets}
                    loading={loading}
                    selectedTicketId={selectedTicketId}
                    onSelectTicket={(ticket) =>
                        setSelectedTicketId(ticket.ticket_id)
                    }
                />
            </main>

            {/* Ticket Inspection Side-Drawer */}
            {activeTicket && (
                <TicketDetailModal
                    ticket={activeTicket}
                    tenantName={activeTenant?.name || activeTenantId || ""}
                    updating={updatingTicket}
                    onClose={() => setSelectedTicketId("")}
                    onUpdateTicket={handleUpdateTicket}
                />
            )}
        </div>
    );
}
