"use client";

import React, { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { useTenant } from "@/context/TenantContext";
import {
    fetchTenantDocuments,
    fetchTenantChunks,
    uploadTenantDocument,
} from "@/lib/api";
import MetricCard from "@/components/MetricCard";
import FileDropzone from "@/components/FileDropzone";
import DocumentTable from "@/components/DocumentTable";
import DocumentViewerModal from "@/components/DocumentViewerModal";
import ChunkExplorer from "@/components/ChunkExplorer";

export default function IngestionHubPage() {
    const {
        activeTenant,
        activeTenantId,
        loading: tenantsLoading,
    } = useTenant();

    const [documents, setDocuments] = useState([]);
    const [loadingDocs, setLoadingDocs] = useState(false);

    const [chunksData, setChunksData] = useState({
        chunks: [],
        total: 0,
        page: 1,
        limit: 50,
        total_pages: 1,
    });
    const [loadingChunks, setLoadingChunks] = useState(false);
    const [chunkDocFilter, setChunkDocFilter] = useState("");
    const [chunkSearch, setChunkSearch] = useState("");
    const [chunkPage, setChunkPage] = useState(1);

    const [viewingDocId, setViewingDocId] = useState("");
    const [targetDocId, setTargetDocId] = useState("");
    const [toast, setToast] = useState(null);
    const [error, setError] = useState(null);

    const showToast = useCallback((type, title, message) => {
        setToast({ type, title, message, id: Date.now() });
    }, []);

    useEffect(() => {
        if (!toast) return;
        const timer = setTimeout(() => setToast(null), 4500);
        return () => clearTimeout(timer);
    }, [toast]);

    const refreshAllData = useCallback(
        async (tenantId, docFilter = chunkDocFilter, search = chunkSearch, page = chunkPage) => {
            if (!tenantId) return;
            setLoadingDocs(true);
            setLoadingChunks(true);
            setError(null);
            try {
                const [docsList, chunkPageData] = await Promise.all([
                    fetchTenantDocuments(tenantId),
                    fetchTenantChunks(tenantId, {
                        page,
                        limit: 50,
                        docId: docFilter,
                        search,
                    }),
                ]);
                setDocuments(docsList);
                setChunksData(chunkPageData);
            } catch (err) {
                setError(
                    err.message || "Failed to load tenant knowledge base from Gateway."
                );
            } finally {
                setLoadingDocs(false);
                setLoadingChunks(false);
            }
        },
        [chunkDocFilter, chunkSearch, chunkPage]
    );

    // Reset filters when activeTenantId changes and load tenant documents + chunks
    useEffect(() => {
        if (!activeTenantId) return;
        let cancelled = false;

        async function loadForActiveTenant() {
            await Promise.resolve();
            if (cancelled) return;
            setChunkDocFilter("");
            setChunkSearch("");
            setChunkPage(1);
            setViewingDocId("");
            setTargetDocId("");
            setLoadingDocs(true);
            setLoadingChunks(true);
            setError(null);

            try {
                const [docsList, chunkPageData] = await Promise.all([
                    fetchTenantDocuments(activeTenantId),
                    fetchTenantChunks(activeTenantId, {
                        page: 1,
                        limit: 50,
                    }),
                ]);
                if (!cancelled) {
                    setDocuments(docsList);
                    setChunksData(chunkPageData);
                }
            } catch (err) {
                if (!cancelled) {
                    setError(
                        err.message ||
                            "Failed to load tenant knowledge base from Gateway."
                    );
                }
            } finally {
                if (!cancelled) {
                    setLoadingDocs(false);
                    setLoadingChunks(false);
                }
            }
        }

        loadForActiveTenant();
        return () => {
            cancelled = true;
        };
    }, [activeTenantId]);

    // Reload chunks when filter, search, or page changes
    useEffect(() => {
        if (!activeTenantId) return;
        let cancelled = false;

        async function reloadChunks() {
            await Promise.resolve();
            if (cancelled) return;
            setLoadingChunks(true);
            try {
                const chunkPageData = await fetchTenantChunks(activeTenantId, {
                    page: chunkPage,
                    limit: 50,
                    docId: chunkDocFilter,
                    search: chunkSearch,
                });
                if (!cancelled) {
                    setChunksData(chunkPageData);
                }
            } catch {
                // Handled by main error banner if needed
            } finally {
                if (!cancelled) {
                    setLoadingChunks(false);
                }
            }
        }

        reloadChunks();
        return () => {
            cancelled = true;
        };
    }, [activeTenantId, chunkDocFilter, chunkSearch, chunkPage]);

    const handleUploadDocument = useCallback(
        async ({ file, overwrite = true, docId = "" }) => {
            if (!activeTenantId) {
                throw new Error("No active tenant selected.");
            }

            const summary = await uploadTenantDocument({
                file,
                tenantId: activeTenantId,
                overwrite,
                docId,
            });

            await refreshAllData(
                activeTenantId,
                chunkDocFilter,
                chunkSearch,
                1
            );
            setChunkPage(1);
            setTargetDocId("");

            showToast(
                "success",
                "Document Indexed to Atlas",
                `${summary.doc_id} (${summary.chunks_created} vector chunks written to doc_vectors).`
            );

            return summary;
        },
        [activeTenantId, chunkDocFilter, chunkSearch, refreshAllData, showToast]
    );

    const totalVectorChunks = documents.reduce(
        (sum, doc) => sum + (Number(doc.chunk_count) || 0),
        0
    );
    const mdCount = documents.filter((d) => d.format === "md").length;
    const jsonCount = documents.filter((d) => d.format === "json").length;
    const similarityThreshold = Number(
        activeTenant?.agent_config?.similarity_threshold ?? 0.7
    ).toFixed(2);
    const maxContextChunks =
        activeTenant?.agent_config?.max_context_chunks ?? 4;

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
                                    ? "Loading Knowledge Base..."
                                    : activeTenant?.name || "Knowledge Base & Ingestion Hub"}
                            </h1>
                            {activeTenantId && (
                                <span className="rounded bg-zinc-900 border border-zinc-800 px-2 py-0.5 font-mono text-xs text-zinc-300">
                                    {activeTenantId}
                                </span>
                            )}
                        </div>
                        <p className="text-xs text-zinc-400 mt-1">
                            Document ingestion pipeline, section chunker, and Atlas{" "}
                            <code className="font-mono">doc_vectors</code> explorer.
                        </p>
                    </div>

                    <div className="flex items-center gap-2">
                        <button
                            type="button"
                            onClick={() => refreshAllData(activeTenantId)}
                            disabled={loadingDocs || !activeTenantId}
                            className="rounded border border-zinc-800 bg-zinc-900 hover:bg-zinc-800 px-3 py-1.5 font-mono text-xs text-zinc-200 disabled:opacity-50 cursor-pointer"
                        >
                            Refresh
                        </button>
                        <Link
                            href="/profile"
                            className="rounded bg-zinc-100 hover:bg-white px-3.5 py-1.5 text-xs font-medium text-zinc-900"
                        >
                            Runtime Config
                        </Link>
                    </div>
                </div>
            </header>

            {/* Main Workspace */}
            <main className="max-w-6xl mx-auto px-6 py-6 space-y-6">
                {error && (
                    <div className="rounded border border-red-900 bg-red-950/50 p-4 flex items-center justify-between gap-4 text-red-200">
                        <div className="text-xs">
                            <p className="font-semibold">Gateway Query Error</p>
                            <p className="text-red-300 mt-0.5 font-mono">{error}</p>
                        </div>
                        <button
                            type="button"
                            onClick={() => refreshAllData(activeTenantId)}
                            className="rounded border border-red-800 bg-red-900 px-3 py-1 text-xs font-medium text-white hover:bg-red-800 cursor-pointer"
                        >
                            Retry
                        </button>
                    </div>
                )}

                {/* 1. Metric Cards */}
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                    <MetricCard
                        label="Ingested Documents"
                        value={documents.length}
                        badge={`${mdCount} .md / ${jsonCount} .json`}
                        subtext={`namespace: ${activeTenantId || "—"}`}
                    />
                    <MetricCard
                        label="Vector Chunks"
                        value={totalVectorChunks}
                        badge="doc_vectors"
                        subtext="index: vector_index (cosine)"
                    />
                    <MetricCard
                        label="Similarity Threshold"
                        value={similarityThreshold}
                        badge={`top_k: ${maxContextChunks}`}
                        subtext={`temp: ${Number(activeTenant?.agent_config?.temperature ?? 0.2).toFixed(2)}`}
                    />
                    <MetricCard
                        label="Embedding Model"
                        value="BAAI/bge-small-en-v1.5"
                        badge="384 dims"
                        subtext="max_seq_length: 512 tokens"
                        monoValue
                    />
                </div>

                {/* 2. File Upload Dropzone */}
                <FileDropzone
                    tenantId={activeTenantId}
                    targetDocId={targetDocId}
                    onClearTargetDocId={() => setTargetDocId("")}
                    onUploadFile={handleUploadDocument}
                />

                {/* 3. Document Management Table */}
                <DocumentTable
                    documents={documents}
                    loading={loadingDocs}
                    onViewDocument={(docId) => setViewingDocId(docId)}
                    onSelectTargetDoc={(docId) => setTargetDocId(docId)}
                    onReuploadDocument={handleUploadDocument}
                />

                {/* 4. Vector Chunk Explorer */}
                <ChunkExplorer
                    chunks={chunksData.chunks}
                    total={chunksData.total}
                    page={chunksData.page}
                    totalPages={chunksData.total_pages}
                    loading={loadingChunks}
                    documents={documents}
                    selectedDocId={chunkDocFilter}
                    searchQuery={chunkSearch}
                    onChangeDocFilter={(val) => {
                        setChunkDocFilter(val);
                        setChunkPage(1);
                    }}
                    onChangeSearch={(val) => {
                        setChunkSearch(val);
                        setChunkPage(1);
                    }}
                    onChangePage={(nextPage) => setChunkPage(nextPage)}
                />
            </main>

            {/* Raw Document Viewer Drawer */}
            {viewingDocId && (
                <DocumentViewerModal
                    tenantId={activeTenantId}
                    docId={viewingDocId}
                    onClose={() => setViewingDocId("")}
                    onRequestReupload={(docId) => setTargetDocId(docId)}
                />
            )}
        </div>
    );
}
