"use client";

import React from "react";
import Link from "next/link";
import { useTenant } from "@/context/TenantContext";

export default function OverviewPage() {
    const { activeTenant, activeTenantId, tenants, loading } = useTenant();

    return (
        <div className="min-h-full bg-zinc-950 text-zinc-100">
            {/* Page Header */}
            <header className="bg-zinc-950 border-b border-zinc-800 px-6 py-4">
                <div className="max-w-5xl mx-auto flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
                    <div>
                        <div className="flex items-center gap-2.5">
                            <h1 className="text-lg font-semibold text-zinc-100">
                                {loading
                                    ? "Loading Tenant Workspace..."
                                    : activeTenant?.name || "Tenant Overview"}
                            </h1>
                            {activeTenantId && (
                                <span className="rounded bg-zinc-900 border border-zinc-800 px-2 py-0.5 font-mono text-xs text-zinc-300">
                                    {activeTenantId}
                                </span>
                            )}
                        </div>
                        <p className="text-xs text-zinc-400 mt-1">
                            Active tenant namespace summary •{" "}
                            <span className="font-mono text-xs text-zinc-300">
                                {tenants.length}
                            </span>{" "}
                            tenants registered in MongoDB Atlas
                        </p>
                    </div>

                    <div className="flex items-center gap-2">
                        <Link
                            href="/profile"
                            className="rounded bg-zinc-100 hover:bg-white px-3.5 py-1.5 text-xs font-medium text-zinc-900"
                        >
                            Edit Profile & Config
                        </Link>
                    </div>
                </div>
            </header>

            <main className="max-w-5xl mx-auto px-6 py-6 space-y-6">
                {/* Summary Panels */}
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <div className="rounded border border-zinc-800 bg-zinc-900/40 p-4">
                        <div className="text-xs font-medium text-zinc-400 mb-2">
                            Business Identity
                        </div>
                        <p className="text-sm font-semibold text-zinc-100 truncate">
                            {activeTenant?.name || "—"}
                        </p>
                        <p className="text-xs text-zinc-400 mt-1 truncate">
                            {activeTenant?.industry || "Sector not configured"}
                        </p>
                        <p className="font-mono text-xs text-zinc-500 mt-2 truncate">
                            {activeTenant?.contact_email || "—"}
                        </p>
                    </div>

                    <div className="rounded border border-zinc-800 bg-zinc-900/40 p-4">
                        <div className="text-xs font-medium text-zinc-400 mb-2">
                            Runtime Parameters
                        </div>
                        <p className="text-sm font-semibold text-zinc-100 truncate">
                            {activeTenant?.agent_config?.agent_tone || "Warm & Professional"}
                        </p>
                        <div className="mt-2 space-y-1 font-mono text-xs text-zinc-400">
                            <div className="flex justify-between">
                                <span>temperature</span>
                                <span className="text-zinc-200">
                                    {Number(activeTenant?.agent_config?.temperature ?? 0.2).toFixed(2)}
                                </span>
                            </div>
                            <div className="flex justify-between">
                                <span>max_context_chunks</span>
                                <span className="text-zinc-200">
                                    {activeTenant?.agent_config?.max_context_chunks ?? 4}
                                </span>
                            </div>
                            <div className="flex justify-between">
                                <span>similarity_threshold</span>
                                <span className="text-zinc-200">
                                    {Number(activeTenant?.agent_config?.similarity_threshold ?? 0.7).toFixed(2)}
                                </span>
                            </div>
                        </div>
                    </div>

                    <div className="rounded border border-zinc-800 bg-zinc-900/40 p-4">
                        <div className="text-xs font-medium text-zinc-400 mb-2">
                            Vector Store Namespace
                        </div>
                        <p className="text-sm font-semibold text-zinc-100">
                            Atlas Pre-Filtered RAG
                        </p>
                        <div className="mt-2 space-y-1 font-mono text-xs text-zinc-400">
                            <div className="flex justify-between">
                                <span>filter.tenant_id</span>
                                <span className="text-zinc-200">
                                    {activeTenantId || "—"}
                                </span>
                            </div>
                            <div className="flex justify-between">
                                <span>index</span>
                                <span className="text-zinc-200">vector_index</span>
                            </div>
                            <div className="flex justify-between">
                                <span>dimensions</span>
                                <span className="text-zinc-200">384</span>
                            </div>
                        </div>
                    </div>
                </div>

                {/* Active System Prompt Preview */}
                {activeTenant?.agent_config?.system_prompt && (
                    <section className="rounded border border-zinc-800 bg-zinc-950">
                        <div className="border-b border-zinc-800 px-5 py-3 flex items-center justify-between bg-zinc-900/40">
                            <h2 className="text-sm font-semibold text-zinc-100">
                                Active System Prompt
                            </h2>
                            <Link
                                href="/profile"
                                className="font-mono text-xs text-zinc-300 hover:text-white underline underline-offset-4"
                            >
                                edit in /profile
                            </Link>
                        </div>
                        <div className="p-5">
                            <pre className="whitespace-pre-wrap rounded bg-zinc-900 border border-zinc-800 p-3.5 font-mono text-xs text-zinc-200 leading-relaxed">
                                {activeTenant.agent_config.system_prompt}
                            </pre>
                        </div>
                    </section>
                )}
            </main>
        </div>
    );
}
