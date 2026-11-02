"use client";

import React, { useState, useEffect } from "react";
import { fetchTenantDocumentDetail } from "@/lib/api";

export default function DocumentViewerModal({
    tenantId,
    docId,
    onClose,
    onRequestReupload,
}) {
    const [detail, setDetail] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [copied, setCopied] = useState(false);

    useEffect(() => {
        if (!tenantId || !docId) return;
        let cancelled = false;

        async function loadDetail() {
            await Promise.resolve();
            if (cancelled) return;
            setLoading(true);
            setError(null);
            try {
                const data = await fetchTenantDocumentDetail(tenantId, docId);
                if (!cancelled) {
                    setDetail(data);
                }
            } catch (err) {
                if (!cancelled) {
                    setError(err.message || "Failed to load document content.");
                }
            } finally {
                if (!cancelled) {
                    setLoading(false);
                }
            }
        }

        loadDetail();
        return () => {
            cancelled = true;
        };
    }, [tenantId, docId]);

    if (!docId) return null;

    const handleCopy = async () => {
        if (!detail?.raw_text) return;
        try {
            await navigator.clipboard.writeText(detail.raw_text);
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
        } catch {
            // Clipboard unavailable
        }
    };

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
                        <div className="flex items-center gap-2">
                            <span className="font-mono text-sm font-semibold text-zinc-100">
                                {detail?.file_name || docId}
                            </span>
                            <span className="rounded bg-zinc-900 border border-zinc-800 px-2 py-0.5 font-mono text-xs text-zinc-300">
                                .{detail?.format || "md"}
                            </span>
                            {detail?.chunk_count !== undefined && (
                                <span className="rounded bg-zinc-900 border border-zinc-800 px-2 py-0.5 font-mono text-xs text-zinc-400">
                                    {detail.chunk_count} chunks
                                </span>
                            )}
                        </div>
                        <p className="font-mono text-xs text-zinc-500 mt-1">
                            tenant_id: {tenantId} • doc_id: {docId}
                        </p>
                    </div>

                    <div className="flex items-center gap-2">
                        {detail?.raw_text && (
                            <button
                                type="button"
                                onClick={handleCopy}
                                className="rounded border border-zinc-800 bg-zinc-900 hover:bg-zinc-800 px-2.5 py-1 font-mono text-xs text-zinc-200 cursor-pointer"
                            >
                                {copied ? "copied" : "copy raw"}
                            </button>
                        )}
                        {onRequestReupload && (
                            <button
                                type="button"
                                onClick={() => {
                                    onClose();
                                    onRequestReupload(docId);
                                }}
                                className="rounded border border-zinc-700 bg-zinc-900 hover:bg-zinc-800 px-2.5 py-1 text-xs font-medium text-zinc-100 cursor-pointer"
                            >
                                Re-upload
                            </button>
                        )}
                        <button
                            type="button"
                            onClick={onClose}
                            className="rounded border border-zinc-800 bg-zinc-900 hover:bg-zinc-800 px-2.5 py-1 font-mono text-xs text-zinc-400 hover:text-zinc-100 cursor-pointer"
                        >
                            ESC / Close
                        </button>
                    </div>
                </div>

                {/* Drawer Body */}
                <div className="flex-1 overflow-y-auto p-6">
                    {loading ? (
                        <div className="rounded border border-zinc-800 bg-zinc-900/30 p-8 text-center font-mono text-xs text-zinc-400">
                            Loading raw document for {docId}...
                        </div>
                    ) : error ? (
                        <div className="rounded border border-red-900 bg-red-950/40 p-4 font-mono text-xs text-red-200">
                            {error}
                        </div>
                    ) : (
                        <pre className="whitespace-pre-wrap break-words rounded border border-zinc-800 bg-zinc-900/50 p-4 font-mono text-xs leading-relaxed text-zinc-200">
                            {detail?.raw_text || ""}
                        </pre>
                    )}
                </div>

                {/* Drawer Footer */}
                <div className="border-t border-zinc-800 px-6 py-3 bg-zinc-900/40 flex items-center justify-between font-mono text-xs text-zinc-500">
                    <span>
                        chars: {detail?.raw_text ? detail.raw_text.length.toLocaleString() : 0}
                    </span>
                    <span>
                        created_at: {detail?.created_at || "—"}
                    </span>
                </div>
            </div>
        </div>
    );
}

