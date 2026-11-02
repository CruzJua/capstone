"use client";

import React, { useRef, useState } from "react";

export default function DocumentTable({
    documents = [],
    loading = false,
    onViewDocument,
    onReuploadDocument,
    onSelectTargetDoc,
}) {
    const fileInputRef = useRef(null);
    const [reuploadDocId, setReuploadDocId] = useState("");
    const [reuploadingId, setReuploadingId] = useState("");

    const handleTriggerRowReupload = (docId) => {
        setReuploadDocId(docId);
        if (onSelectTargetDoc) {
            onSelectTargetDoc(docId);
        }
        if (fileInputRef.current) {
            fileInputRef.current.value = "";
            fileInputRef.current.click();
        }
    };

    const handleQuickFileChange = async (e) => {
        const file = e.target.files?.[0];
        if (!file || !reuploadDocId) return;

        setReuploadingId(reuploadDocId);
        try {
            await onReuploadDocument({
                file,
                overwrite: true,
                docId: reuploadDocId,
            });
        } finally {
            setReuploadingId("");
            if (fileInputRef.current) {
                fileInputRef.current.value = "";
            }
        }
    };

    return (
        <section className="rounded border border-zinc-800 bg-zinc-950">
            <input
                ref={fileInputRef}
                type="file"
                accept=".md,.json"
                onChange={handleQuickFileChange}
                className="hidden"
            />

            <div className="border-b border-zinc-800 px-5 py-3 flex items-center justify-between bg-zinc-900/40">
                <div className="flex items-center gap-2.5">
                    <h2 className="text-sm font-semibold text-zinc-100">
                        Ingested Documents
                    </h2>
                    <span className="rounded bg-zinc-900 border border-zinc-800 px-2 py-0.5 font-mono text-xs text-zinc-300">
                        {documents.length}
                    </span>
                </div>
                <span className="font-mono text-xs text-zinc-500">
                    collection: doc_vectors (grouped by doc_id)
                </span>
            </div>

            {loading ? (
                <div className="p-8 text-center font-mono text-xs text-zinc-400">
                    Querying tenant documents from MongoDB Atlas...
                </div>
            ) : documents.length === 0 ? (
                <div className="p-8 text-center">
                    <p className="text-sm font-medium text-zinc-300">
                        No documents ingested for this tenant yet.
                    </p>
                    <p className="font-mono text-xs text-zinc-500 mt-1">
                        Drop a .md or .json file above to index chunks into doc_vectors.
                    </p>
                </div>
            ) : (
                <div className="overflow-x-auto">
                    <table className="w-full text-left border-collapse">
                        <thead>
                            <tr className="border-b border-zinc-800 bg-zinc-900/20 font-mono text-[11px] uppercase text-zinc-400">
                                <th className="py-2.5 px-5 font-medium">doc_id</th>
                                <th className="py-2.5 px-4 font-medium">Format</th>
                                <th className="py-2.5 px-4 font-medium">Chunks</th>
                                <th className="py-2.5 px-4 font-medium">Chars</th>
                                <th className="py-2.5 px-4 font-medium">Last Indexed</th>
                                <th className="py-2.5 px-5 font-medium text-right">
                                    Actions
                                </th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-zinc-800/80 text-xs">
                            {documents.map((doc) => {
                                const isRowReuploading =
                                    reuploadingId === doc.doc_id;
                                return (
                                    <tr
                                        key={doc.doc_id}
                                        className="hover:bg-zinc-900/30 transition-colors"
                                    >
                                        <td className="py-2.5 px-5 font-mono text-xs font-medium text-zinc-100">
                                            {doc.doc_id}
                                        </td>
                                        <td className="py-2.5 px-4">
                                            <span className="rounded bg-zinc-900 border border-zinc-800 px-1.5 py-0.5 font-mono text-xs text-zinc-300 uppercase">
                                                .{doc.format || "md"}
                                            </span>
                                        </td>
                                        <td className="py-2.5 px-4 font-mono text-xs text-zinc-200">
                                            {doc.chunk_count}
                                        </td>
                                        <td className="py-2.5 px-4 font-mono text-xs text-zinc-400">
                                            {(doc.total_chars || 0).toLocaleString()}
                                        </td>
                                        <td className="py-2.5 px-4 font-mono text-xs text-zinc-400">
                                            {doc.created_at
                                                ? new Date(
                                                      doc.created_at
                                                  ).toISOString().slice(0, 19).replace("T", " ")
                                                : "—"}
                                        </td>
                                        <td className="py-2.5 px-5 text-right">
                                            <div className="inline-flex items-center justify-end gap-2">
                                                <button
                                                    type="button"
                                                    onClick={() =>
                                                        onViewDocument(doc.doc_id)
                                                    }
                                                    className="rounded border border-zinc-800 bg-zinc-900 hover:bg-zinc-800 px-2.5 py-1 text-xs font-medium text-zinc-200 cursor-pointer"
                                                >
                                                    View
                                                </button>
                                                <button
                                                    type="button"
                                                    disabled={isRowReuploading}
                                                    onClick={() =>
                                                        handleTriggerRowReupload(
                                                            doc.doc_id
                                                        )
                                                    }
                                                    className="rounded border border-zinc-700 bg-zinc-900 hover:bg-zinc-800 px-2.5 py-1 text-xs font-medium text-zinc-100 disabled:opacity-50 cursor-pointer"
                                                >
                                                    {isRowReuploading
                                                        ? "Indexing..."
                                                        : "Re-upload"}
                                                </button>
                                            </div>
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

