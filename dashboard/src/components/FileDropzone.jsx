"use client";

import React, { useRef, useState } from "react";

export default function FileDropzone({
    tenantId,
    onUploadFile,
    targetDocId = "",
    onClearTargetDocId,
}) {
    const fileInputRef = useRef(null);
    const [dragActive, setDragActive] = useState(false);
    const [overwrite, setOverwrite] = useState(true);
    const [stage, setStage] = useState("idle"); // idle | uploading | embedding | ready | error
    const [statusMessage, setStatusMessage] = useState("");
    const [selectedFileName, setSelectedFileName] = useState("");

    const validateAndProcessFile = async (file) => {
        if (!file) return;

        const lowerName = file.name.toLowerCase();
        if (!lowerName.endsWith(".md") && !lowerName.endsWith(".json")) {
            setStage("error");
            setStatusMessage("Invalid file type. Only .md and .json files are accepted.");
            return;
        }

        setSelectedFileName(file.name);
        setStage("uploading");
        setStatusMessage(`Uploading ${file.name} to Gateway staging...`);

        const embeddingTimer = setTimeout(() => {
            setStage((current) =>
                current === "uploading" ? "embedding" : current
            );
            setStatusMessage(
                `Embedding chunks with BAAI/bge-small-en-v1.5 -> doc_vectors...`
            );
        }, 450);

        try {
            const summary = await onUploadFile({
                file,
                overwrite: targetDocId ? true : overwrite,
                docId: targetDocId || "",
            });
            clearTimeout(embeddingTimer);
            setStage("ready");
            setStatusMessage(
                `Ready — ${summary.doc_id} (${summary.chunks_created} chunks indexed)`
            );
            if (fileInputRef.current) {
                fileInputRef.current.value = "";
            }
        } catch (err) {
            clearTimeout(embeddingTimer);
            setStage("error");
            setStatusMessage(err.message || "Ingestion failed.");
            if (fileInputRef.current) {
                fileInputRef.current.value = "";
            }
        }
    };

    const handleDragOver = (e) => {
        e.preventDefault();
        e.stopPropagation();
        if (!dragActive) setDragActive(true);
    };

    const handleDragLeave = (e) => {
        e.preventDefault();
        e.stopPropagation();
        setDragActive(false);
    };

    const handleDrop = (e) => {
        e.preventDefault();
        e.stopPropagation();
        setDragActive(false);
        const droppedFile = e.dataTransfer?.files?.[0];
        if (droppedFile) {
            validateAndProcessFile(droppedFile);
        }
    };

    const handleFileSelect = (e) => {
        const pickedFile = e.target.files?.[0];
        if (pickedFile) {
            validateAndProcessFile(pickedFile);
        }
    };

    const isBusy = stage === "uploading" || stage === "embedding";

    return (
        <section className="rounded border border-zinc-800 bg-zinc-950">
            <div className="border-b border-zinc-800 px-5 py-3 flex flex-wrap items-center justify-between gap-3 bg-zinc-900/40">
                <div className="flex items-center gap-2.5">
                    <h2 className="text-sm font-semibold text-zinc-100">
                        Document Ingestion Pipeline
                    </h2>
                    <span className="rounded bg-zinc-900 border border-zinc-800 px-2 py-0.5 font-mono text-xs text-zinc-400">
                        .md / .json
                    </span>
                    {targetDocId && (
                        <span className="inline-flex items-center gap-2 rounded bg-zinc-800 border border-zinc-700 px-2 py-0.5 font-mono text-xs text-zinc-100">
                            target doc_id: {targetDocId}
                            {onClearTargetDocId && (
                                <button
                                    type="button"
                                    onClick={onClearTargetDocId}
                                    className="text-zinc-400 hover:text-zinc-100 ml-1 cursor-pointer"
                                    title="Clear target doc_id"
                                >
                                    ×
                                </button>
                            )}
                        </span>
                    )}
                </div>

                <label className="inline-flex items-center gap-2 text-xs text-zinc-300 cursor-pointer select-none">
                    <input
                        type="checkbox"
                        checked={targetDocId ? true : overwrite}
                        disabled={Boolean(targetDocId) || isBusy}
                        onChange={(e) => setOverwrite(e.target.checked)}
                        className="h-3.5 w-3.5 rounded border-zinc-700 bg-zinc-900 accent-zinc-200 cursor-pointer"
                    />
                    <span>Overwrite if document already exists</span>
                </label>
            </div>

            <div className="p-5">
                <div
                    onDragOver={handleDragOver}
                    onDragLeave={handleDragLeave}
                    onDrop={handleDrop}
                    className={`rounded border border-dashed px-6 py-7 text-center transition-colors ${
                        dragActive
                            ? "border-zinc-400 bg-zinc-900/80"
                            : "border-zinc-800 hover:border-zinc-700 bg-zinc-900/25"
                    }`}
                >
                    <input
                        ref={fileInputRef}
                        type="file"
                        accept=".md,.json"
                        onChange={handleFileSelect}
                        disabled={isBusy || !tenantId}
                        className="hidden"
                    />

                    <p className="text-sm text-zinc-200 font-medium">
                        {targetDocId
                            ? `Drop replacement file for '${targetDocId}' or browse from disk`
                            : "Drop a Markdown (.md) or JSON (.json) document here"}
                    </p>
                    <p className="font-mono text-xs text-zinc-500 mt-1">
                        POST /api/documents/upload → scripts.ingest_uploaded_document → {tenantId || "tenant"}.doc_vectors
                    </p>

                    <div className="mt-4 flex items-center justify-center gap-3">
                        <button
                            type="button"
                            disabled={isBusy || !tenantId}
                            onClick={() => fileInputRef.current?.click()}
                            className="rounded border border-zinc-700 bg-zinc-900 hover:bg-zinc-800 px-3.5 py-1.5 text-xs font-medium text-zinc-100 disabled:opacity-50 cursor-pointer transition-colors"
                        >
                            {isBusy ? "Processing..." : "Browse Files"}
                        </button>
                    </div>
                </div>

                {/* Pipeline Stage Indicator */}
                <div className="mt-3 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 rounded border border-zinc-800/80 bg-zinc-900/30 px-3.5 py-2 font-mono text-xs">
                    <div className="flex items-center gap-3">
                        <span
                            className={
                                stage === "uploading"
                                    ? "text-zinc-100 font-semibold"
                                    : stage === "embedding" || stage === "ready"
                                    ? "text-zinc-400"
                                    : "text-zinc-600"
                            }
                        >
                            1. Uploading...
                        </span>
                        <span className="text-zinc-700">→</span>
                        <span
                            className={
                                stage === "embedding"
                                    ? "text-zinc-100 font-semibold"
                                    : stage === "ready"
                                    ? "text-zinc-400"
                                    : "text-zinc-600"
                            }
                        >
                            2. Embedding...
                        </span>
                        <span className="text-zinc-700">→</span>
                        <span
                            className={
                                stage === "ready"
                                    ? "text-emerald-400 font-semibold"
                                    : "text-zinc-600"
                            }
                        >
                            3. Ready
                        </span>
                    </div>

                    <div className="truncate">
                        {stage === "idle" ? (
                            <span className="text-zinc-500">
                                status: idle {selectedFileName ? `(${selectedFileName})` : ""}
                            </span>
                        ) : stage === "error" ? (
                            <span className="text-red-400">{statusMessage}</span>
                        ) : stage === "ready" ? (
                            <span className="text-emerald-400">{statusMessage}</span>
                        ) : (
                            <span className="text-zinc-300">{statusMessage}</span>
                        )}
                    </div>
                </div>
            </div>
        </section>
    );
}

