"use client";

import React from "react";
import Link from "next/link";
import { useTenant } from "@/context/TenantContext";

export default function TicketsPage() {
    const { activeTenant, activeTenantId } = useTenant();

    return (
        <div className="min-h-full bg-zinc-950 text-zinc-100">
            {/* Page Header */}
            <header className="bg-zinc-950 border-b border-zinc-800 px-6 py-4">
                <div className="max-w-5xl mx-auto flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
                    <div>
                        <div className="flex items-center gap-2.5">
                            <h1 className="text-lg font-semibold text-zinc-100">
                                Ticket Review Queue
                            </h1>
                            {activeTenantId && (
                                <span className="rounded bg-zinc-900 border border-zinc-800 px-2 py-0.5 font-mono text-xs text-zinc-300">
                                    {activeTenantId}
                                </span>
                            )}
                        </div>
                        <p className="text-xs text-zinc-400 mt-1">
                            Grounded interaction logs and escalation queue for{" "}
                            <span className="text-zinc-200 font-medium">
                                {activeTenant?.name || activeTenantId || "active tenant"}
                            </span>
                        </p>
                    </div>
                    <Link
                        href="/profile"
                        className="rounded border border-zinc-800 bg-zinc-900 px-3 py-1.5 text-xs font-medium text-zinc-200 hover:bg-zinc-800"
                    >
                        Runtime Thresholds
                    </Link>
                </div>
            </header>

            <main className="max-w-5xl mx-auto px-6 py-6">
                <section className="rounded border border-zinc-800 bg-zinc-950">
                    <div className="border-b border-zinc-800 px-5 py-3 flex items-center justify-between bg-zinc-900/40">
                        <span className="text-xs font-medium text-zinc-300">
                            Queue Entries
                        </span>
                        <span className="font-mono text-xs text-zinc-500">
                            tenant_id: {activeTenantId || "loading"}
                        </span>
                    </div>
                    <div className="p-8 text-center">
                        <p className="text-sm font-medium text-zinc-200">
                            No escalated tickets recorded for this tenant.
                        </p>
                        <p className="text-xs text-zinc-500 max-w-md mx-auto mt-1 leading-relaxed">
                            Storefront sessions with <code className="font-mono">[rationale]</code> and{" "}
                            <code className="font-mono">[label]</code> outputs will populate this table when logged.
                        </p>
                    </div>
                </section>
            </main>
        </div>
    );
}
