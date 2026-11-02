"use client";

import React, { useState } from "react";

const MAX_MODEL_TOKENS = 512;

export default function ChunkExplorer({
    chunks = [],
    total = 0,
    page = 1,
    totalPages = 1,
    loading = false,
    documents = [],
    selectedDocId = "",
    searchQuery = "",
    onChangeDocFilter,
    onChangeSearch,
    onChangePage,
}) {
    const [activeChunk, setActiveChunk] = useState(null);

    return (
        <section className="rounded border border-zinc-800 bg-zinc-950">
            {/* Header */}
            <div className="border-b border-zinc-800 px-5 py-3 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 bg-zinc-900/40">
                <div className="flex flex-wrap items-center gap-2.5">
                    <h2 className="text-sm font-semibold text-zinc-100">
                        Vector Chunk Explorer
                    </h2>
                    <span className="rounded bg-zinc-900 border border-zinc-800 px-2 py-0.5 font-mono text-xs text-zinc-300">
                        {total} chunks
                    </span>
                    <span className="rounded bg-zinc-900 border border-zinc-800 px-2 py-0.5 font-mono text-xs text-zinc-400">
                        [v2.1 preview] Manual chunk editing coming soon
                    </span>
                </div>

                {/* Filters */}
                <div className="flex flex-wrap items-center gap-2">
                    <select
                        aria-label="Filter chunks by document"
                        value={selectedDocId}
                        onChange={(e) => onChangeDocFilter(e.target.value)}
                        className="bg-zinc-900 border border-zinc-800 rounded px-2.5 py-1 font-mono text-xs text-zinc-200 focus:border-zinc-600 focus:outline-none"
                    >
                        <option value="">all documents ({documents.length})</option>
                        {documents.map((doc) => (
                            <option key={doc.doc_id} value={doc.doc_id}>
                                {doc.doc_id} ({doc.chunk_count})
                            </option>
                        ))}
                    </select>

                    <input
                        type="text"
                        value={searchQuery}
                        onChange={(e) => onChangeSearch(e.target.value)}
                        placeholder="Filter chunk text or section..."
                        className="bg-zinc-900 border border-zinc-800 rounded px-2.5 py-1 text-xs text-zinc-100 focus:border-zinc-600 focus:outline-none w-52"
                    />
                </div>
            </div>

            {/* Table */}
            {loading ? (
                <div className="p-8 text-center font-mono text-xs text-zinc-400">
                    Loading vector chunks from doc_vectors...
                </div>
            ) : chunks.length === 0 ? (
                <div className="p-8 text-center font-mono text-xs text-zinc-500">
                    No vector chunks match the current filter.
                </div>
            ) : (
                <div className="overflow-x-auto">
                    <table className="w-full text-left border-collapse">
                        <thead>
                            <tr className="border-b border-zinc-800 bg-zinc-900/20 font-mono text-[11px] uppercase text-zinc-400">
                                <th className="py-2.5 px-5 font-medium">Index</th>
                                <th className="py-2.5 px-4 font-medium">doc_id</th>
                                <th className="py-2.5 px-4 font-medium">Section Header</th>
                                <th className="py-2.5 px-4 font-medium">Text Snippet</th>
                                <th className="py-2.5 px-4 font-medium">Chars</th>
                                <th className="py-2.5 px-4 font-medium">Tokens</th>
                                <th className="py-2.5 px-5 font-medium text-right">
                                    Inspect
                                </th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-zinc-800/80 text-xs">
                            {chunks.map((chunk) => {
                                const withinBudget =
                                    chunk.token_estimate <= MAX_MODEL_TOKENS;
                                return (
                                    <tr
                                        key={`${chunk.doc_id}-${chunk.chunk_index}`}
                                        onClick={() => setActiveChunk(chunk)}
                                        className="hover:bg-zinc-900/30 transition-colors cursor-pointer"
                                    >
                                        <td className="py-2.5 px-5 font-mono text-xs text-zinc-300">
                                            #{chunk.chunk_index}
                                        </td>
                                        <td className="py-2.5 px-4 font-mono text-xs text-zinc-200">
                                            {chunk.doc_id}
                                        </td>
                                        <td className="py-2.5 px-4 text-zinc-300 max-w-[180px] truncate">
                                            {chunk.section}
                                        </td>
                                        <td className="py-2.5 px-4 font-mono text-xs text-zinc-400 max-w-md truncate">
                                            {chunk.snippet}
                                        </td>
                                        <td className="py-2.5 px-4 font-mono text-xs text-zinc-400">
                                            {chunk.char_count}
                                        </td>
                                        <td className="py-2.5 px-4">
                                            <span
                                                className={`rounded border px-1.5 py-0.5 font-mono text-xs ${
                                                    withinBudget
                                                        ? "bg-zinc-900 border-zinc-800 text-zinc-300"
                                                        : "bg-amber-950/50 border-amber-800 text-amber-300"
                                                }`}
                                            >
                                                ~{chunk.token_estimate}/{MAX_MODEL_TOKENS}
                                            </span>
                                        </td>
                                        <td className="py-2.5 px-5 text-right">
                                            <button
                                                type="button"
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    setActiveChunk(chunk);
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

            {/* Pagination Footer */}
            <div className="border-t border-zinc-800 px-5 py-3 bg-zinc-900/40 flex items-center justify-between font-mono text-xs text-zinc-400">
                <span>
                    page {page} of {totalPages} • {total} total chunks
                </span>
                <div className="flex items-center gap-2">
                    <button
                        type="button"
                        disabled={page <= 1 || loading}
                        onClick={() => onChangePage(page - 1)}
                        className="rounded border border-zinc-800 bg-zinc-900 hover:bg-zinc-800 px-2.5 py-1 text-zinc-200 disabled:opacity-40 disabled:pointer-events-none cursor-pointer"
                    >
                        Prev
                    </button>
                    <button
                        type="button"
                        disabled={page >= totalPages || loading}
                        onClick={() => onChangePage(page + 1)}
                        className="rounded border border-zinc-800 bg-zinc-900 hover:bg-zinc-800 px-2.5 py-1 text-zinc-200 disabled:opacity-40 disabled:pointer-events-none cursor-pointer"
                    >
                        Next
                    </button>
                </div>
            </div>

            {/* Chunk Inspection Modal */}
            {activeChunk && (
                <div
                    className="fixed inset-0 z-50 bg-black/75 flex items-center justify-center p-4"
                    onClick={() => setActiveChunk(null)}
                >
                    <div
                        className="w-full max-w-2xl rounded border border-zinc-800 bg-zinc-950 overflow-hidden"
                        onClick={(e) => e.stopPropagation()}
                    >
                        <div className="border-b border-zinc-800 px-5 py-3.5 flex items-center justify-between bg-zinc-900/40">
                            <div className="flex flex-wrap items-center gap-2">
                                <span className="font-mono text-xs font-semibold text-zinc-100">
                                    {activeChunk.doc_id}
                                </span>
                                <span className="rounded bg-zinc-900 border border-zinc-800 px-2 py-0.5 font-mono text-xs text-zinc-300">
                                    chunk #{activeChunk.chunk_index}
                                </span>
                                <span className="rounded bg-zinc-900 border border-zinc-800 px-2 py-0.5 font-mono text-xs text-zinc-400">
                                    ~{activeChunk.token_estimate} / {MAX_MODEL_TOKENS} tokens
                                </span>
                            </div>
                            <button
                                type="button"
                                onClick={() => setActiveChunk(null)}
                                className="rounded border border-zinc-800 bg-zinc-900 hover:bg-zinc-800 px-2.5 py-1 font-mono text-xs text-zinc-300 cursor-pointer"
                            >
                                Close
                            </button>
                        </div>

                        <div className="p-5 space-y-3">
                            <div className="flex items-center justify-between font-mono text-xs text-zinc-400">
                                <span>section: {activeChunk.section}</span>
                                <span>
                                    {activeChunk.char_count} chars • {activeChunk.word_count} words
                                </span>
                            </div>

                            <pre className="max-h-96 overflow-y-auto whitespace-pre-wrap break-words rounded border border-zinc-800 bg-zinc-900 p-4 font-mono text-xs leading-relaxed text-zinc-100">
                                {activeChunk.text}
                            </pre>

                            <div className="flex items-center justify-between pt-1 font-mono text-xs text-zinc-500">
                                <span>embedding: BAAI/bge-small-en-v1.5 (384 dims)</span>
                                <span>[v2.1 preview] Manual chunk editing coming soon</span>
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </section>
    );
}

