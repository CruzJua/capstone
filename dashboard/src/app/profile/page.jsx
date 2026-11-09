"use client";

import React, { useState, useEffect, useCallback } from "react";
import { useTenant } from "@/context/TenantContext";
import { fetchTenantConfig, updateTenantConfig } from "@/lib/api";
import ConfigSlider from "@/components/ConfigSlider";
import { originsToText, widgetConfigPayload } from "@/lib/origins.mjs";

const TONE_PRESETS = [
    "Warm & Professional",
    "Rugged & Direct",
    "Empathetic & Clinical",
    "Technical & Concise",
    "Friendly & Conversational",
];

const INITIAL_FORM = {
    tenant_id: "",
    name: "",
    industry: "",
    contact_email: "",
    team_name: "",
    // One origin per line, as typed (widget_config.allowed_origins).
    allowed_origins: "",
    agent_config: {
        system_prompt: "",
        agent_tone: "Warm & Professional",
        temperature: 0.2,
        max_context_chunks: 4,
        similarity_threshold: 0.7,
    },
    updated_at: null,
};

function normalizeDocToForm(doc) {
    return {
        tenant_id: doc?.tenant_id || "",
        name: doc?.name || "",
        industry: doc?.industry || "",
        contact_email: doc?.contact_email || "",
        team_name: doc?.team_name || "",
        allowed_origins: originsToText(doc?.widget_config?.allowed_origins),
        agent_config: {
            system_prompt: doc?.agent_config?.system_prompt || "",
            agent_tone: doc?.agent_config?.agent_tone || "Warm & Professional",
            temperature:
                typeof doc?.agent_config?.temperature === "number"
                    ? doc.agent_config.temperature
                    : 0.2,
            max_context_chunks:
                typeof doc?.agent_config?.max_context_chunks === "number"
                    ? doc.agent_config.max_context_chunks
                    : 4,
            similarity_threshold:
                typeof doc?.agent_config?.similarity_threshold === "number"
                    ? doc.agent_config.similarity_threshold
                    : 0.7,
        },
        updated_at: doc?.updated_at || null,
    };
}

export default function ProfilePage() {
    const {
        activeTenantId,
        updateTenantInList,
        loading: tenantsLoading,
    } = useTenant();

    const [form, setForm] = useState(INITIAL_FORM);
    const [savedSnapshot, setSavedSnapshot] = useState(INITIAL_FORM);
    const [loadingConfig, setLoadingConfig] = useState(false);
    const [saving, setSaving] = useState(false);
    const [loadError, setLoadError] = useState(null);
    const [toast, setToast] = useState(null);

    const showToast = useCallback((type, title, message) => {
        setToast({ type, title, message, id: Date.now() });
    }, []);

    useEffect(() => {
        if (!toast) return;
        const timer = setTimeout(() => {
            setToast(null);
        }, 4500);
        return () => clearTimeout(timer);
    }, [toast]);

    const loadActiveTenantConfig = useCallback(async (tenantId) => {
        if (!tenantId) return;
        setLoadingConfig(true);
        setLoadError(null);
        try {
            const doc = await fetchTenantConfig(tenantId);
            const normalized = normalizeDocToForm(doc);
            setForm(normalized);
            setSavedSnapshot(normalized);
        } catch (err) {
            setLoadError(
                err.message || "Failed to load tenant configuration from Gateway."
            );
        } finally {
            setLoadingConfig(false);
        }
    }, []);

    useEffect(() => {
        if (!activeTenantId) return;
        let cancelled = false;

        async function fetchConfigForTenant() {
            await Promise.resolve();
            if (cancelled) return;
            setLoadingConfig(true);
            setLoadError(null);
            try {
                const doc = await fetchTenantConfig(activeTenantId);
                if (!cancelled) {
                    const normalized = normalizeDocToForm(doc);
                    setForm(normalized);
                    setSavedSnapshot(normalized);
                }
            } catch (err) {
                if (!cancelled) {
                    setLoadError(
                        err.message ||
                            "Failed to load tenant configuration from Gateway."
                    );
                }
            } finally {
                if (!cancelled) {
                    setLoadingConfig(false);
                }
            }
        }

        fetchConfigForTenant();
        return () => {
            cancelled = true;
        };
    }, [activeTenantId]);

    const handleIdentityChange = (field, value) => {
        setForm((prev) => ({
            ...prev,
            [field]: value,
        }));
    };

    const handleAgentConfigChange = (field, value) => {
        setForm((prev) => ({
            ...prev,
            agent_config: {
                ...prev.agent_config,
                [field]: value,
            },
        }));
    };

    const handleReset = () => {
        setForm(savedSnapshot);
        showToast(
            "info",
            "Changes Discarded",
            "Reverted fields to the last saved MongoDB configuration."
        );
    };

    const handleSave = async (e) => {
        if (e) e.preventDefault();
        if (!activeTenantId) return;

        setSaving(true);
        try {
            const widgetConfig = widgetConfigPayload(
                form.allowed_origins,
                savedSnapshot.allowed_origins
            );
            const payload = {
                name: form.name,
                industry: form.industry,
                contact_email: form.contact_email,
                team_name: form.team_name,
                ...(widgetConfig ? { widget_config: widgetConfig } : {}),
                agent_config: {
                    system_prompt: form.agent_config.system_prompt,
                    agent_tone: form.agent_config.agent_tone,
                    temperature: Number(form.agent_config.temperature),
                    max_context_chunks: Number(form.agent_config.max_context_chunks),
                    similarity_threshold: Number(form.agent_config.similarity_threshold),
                },
            };

            const updatedDoc = await updateTenantConfig(activeTenantId, payload);
            const normalized = normalizeDocToForm(updatedDoc);
            setForm(normalized);
            setSavedSnapshot(normalized);
            updateTenantInList(updatedDoc);

            showToast(
                "success",
                "Configuration Saved to MongoDB Atlas",
                `Updated runtime profile for ${normalized.name} (${normalized.tenant_id}).`
            );
        } catch (err) {
            showToast(
                "error",
                "Failed to Save Configuration",
                err.message || "Could not update tenant configuration."
            );
        } finally {
            setSaving(false);
        }
    };

    const hasUnsavedChanges =
        JSON.stringify({
            name: form.name,
            industry: form.industry,
            contact_email: form.contact_email,
            team_name: form.team_name,
            allowed_origins: form.allowed_origins,
            agent_config: form.agent_config,
        }) !==
        JSON.stringify({
            name: savedSnapshot.name,
            industry: savedSnapshot.industry,
            contact_email: savedSnapshot.contact_email,
            team_name: savedSnapshot.team_name,
            allowed_origins: savedSnapshot.allowed_origins,
            agent_config: savedSnapshot.agent_config,
        });

    return (
        <div className="min-h-full bg-zinc-950 text-zinc-100">
            {/* Status Notification */}
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
                                : toast.type === "info"
                                ? "bg-zinc-900 border-zinc-700 text-zinc-100"
                                : "bg-zinc-900 border-emerald-700 text-zinc-100"
                        }`}
                    >
                        <p className="font-medium text-xs uppercase tracking-wide">
                            {toast.title}
                        </p>
                        <p className="text-xs text-zinc-300 mt-1">{toast.message}</p>
                    </div>
                </div>
            )}

            {/* Page Header */}
            <header className="bg-zinc-950 border-b border-zinc-800 px-6 py-4">
                <div className="max-w-5xl mx-auto flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
                    <div>
                        <div className="flex items-center gap-2.5">
                            <h1 className="text-lg font-semibold text-zinc-100">
                                Tenant Profile & Runtime Configuration
                            </h1>
                            {form.tenant_id && (
                                <span
                                    data-testid="tenant-id-badge"
                                    className="rounded bg-zinc-900 border border-zinc-800 px-2 py-0.5 font-mono text-xs text-zinc-300"
                                >
                                    {form.tenant_id}
                                </span>
                            )}
                        </div>
                        <div className="text-xs text-zinc-400 mt-1 flex flex-wrap items-center gap-3">
                            <span>
                                Storefront identity and RAG / LLM runtime parameters persisted in MongoDB Atlas.
                            </span>
                            {form.updated_at && (
                                <span className="font-mono text-xs text-zinc-500">
                                    updated_at: {new Date(form.updated_at).toISOString()}
                                </span>
                            )}
                        </div>
                    </div>

                    <div className="flex items-center gap-2">
                        <button
                            type="button"
                            onClick={handleReset}
                            disabled={!hasUnsavedChanges || saving || loadingConfig}
                            className="rounded border border-zinc-800 bg-zinc-900 px-3 py-1.5 text-xs font-medium text-zinc-200 hover:bg-zinc-800 disabled:opacity-40 disabled:pointer-events-none cursor-pointer"
                        >
                            Reset
                        </button>
                        <button
                            type="button"
                            onClick={handleSave}
                            disabled={saving || loadingConfig || !activeTenantId}
                            className="rounded bg-zinc-100 hover:bg-white px-3.5 py-1.5 text-xs font-medium text-zinc-900 disabled:opacity-50 disabled:pointer-events-none cursor-pointer"
                        >
                            {saving ? "Saving..." : "Save Configuration"}
                        </button>
                    </div>
                </div>
            </header>

            {/* Main Content */}
            <main className="max-w-5xl mx-auto px-6 py-6">
                {loadError && (
                    <div className="mb-6 rounded border border-red-900 bg-red-950/50 p-4 flex items-center justify-between gap-4 text-red-200">
                        <div className="text-sm">
                            <p className="font-medium">Failed to load tenant configuration</p>
                            <p className="text-xs text-red-300 mt-0.5">{loadError}</p>
                        </div>
                        <button
                            type="button"
                            onClick={() => loadActiveTenantConfig(activeTenantId)}
                            className="rounded border border-red-800 bg-red-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-800"
                        >
                            Retry
                        </button>
                    </div>
                )}

                {tenantsLoading || loadingConfig ? (
                    <div className="rounded border border-zinc-800 bg-zinc-900/40 p-8 text-center">
                        <p className="text-sm text-zinc-300">
                            Loading tenant configuration from MongoDB Atlas...
                        </p>
                        <p className="font-mono text-xs text-zinc-500 mt-1">
                            GET /api/tenants/{activeTenantId || "..."}/config
                        </p>
                    </div>
                ) : (
                    <form onSubmit={handleSave} className="space-y-6">
                        {/* Card 1: Business Identity */}
                        <section className="rounded border border-zinc-800 bg-zinc-950">
                            <div className="border-b border-zinc-800 px-5 py-3.5 flex items-center justify-between bg-zinc-900/40">
                                <div>
                                    <h2 className="text-sm font-semibold text-zinc-100">
                                        Business Identity
                                    </h2>
                                    <p className="text-xs text-zinc-400">
                                        Organization metadata for this tenant namespace.
                                    </p>
                                </div>

                                <div className="flex items-center gap-2">
                                    <span className="text-xs text-zinc-500">tenant_id:</span>
                                    <span className="rounded bg-zinc-900 border border-zinc-800 px-2 py-0.5 font-mono text-xs text-zinc-200">
                                        {form.tenant_id || activeTenantId}
                                    </span>
                                </div>
                            </div>

                            <div className="p-5 grid grid-cols-1 md:grid-cols-2 gap-4">
                                {/* Business Name */}
                                <div>
                                    <label
                                        htmlFor="business-name"
                                        className="block text-xs font-medium text-zinc-300 mb-1.5"
                                    >
                                        Business Name
                                    </label>
                                    <input
                                        id="business-name"
                                        type="text"
                                        required
                                        value={form.name}
                                        onChange={(e) =>
                                            handleIdentityChange("name", e.target.value)
                                        }
                                        placeholder="Iron & Oak Provision Co."
                                        className="w-full bg-zinc-900 border border-zinc-800 rounded px-3 py-2 text-sm text-zinc-100 focus:border-zinc-600 focus:outline-none"
                                    />
                                </div>

                                {/* Sector / Industry */}
                                <div>
                                    <label
                                        htmlFor="business-industry"
                                        className="block text-xs font-medium text-zinc-300 mb-1.5"
                                    >
                                        Sector / Industry
                                    </label>
                                    <input
                                        id="business-industry"
                                        type="text"
                                        value={form.industry}
                                        onChange={(e) =>
                                            handleIdentityChange("industry", e.target.value)
                                        }
                                        placeholder="Outdoor Apparel & Heritage Gear"
                                        className="w-full bg-zinc-900 border border-zinc-800 rounded px-3 py-2 text-sm text-zinc-100 focus:border-zinc-600 focus:outline-none"
                                    />
                                </div>

                                {/* Support Email */}
                                <div>
                                    <label
                                        htmlFor="contact-email"
                                        className="block text-xs font-medium text-zinc-300 mb-1.5"
                                    >
                                        Support Email
                                    </label>
                                    <input
                                        id="contact-email"
                                        type="email"
                                        required
                                        value={form.contact_email}
                                        onChange={(e) =>
                                            handleIdentityChange(
                                                "contact_email",
                                                e.target.value
                                            )
                                        }
                                        placeholder="support@ironandoak.com"
                                        className="w-full bg-zinc-900 border border-zinc-800 rounded px-3 py-2 text-sm text-zinc-100 focus:border-zinc-600 focus:outline-none"
                                    />
                                </div>

                                {/* Team / Admin Name */}
                                <div>
                                    <label
                                        htmlFor="team-name"
                                        className="block text-xs font-medium text-zinc-300 mb-1.5"
                                    >
                                        Team / Admin Name
                                    </label>
                                    <input
                                        id="team-name"
                                        type="text"
                                        value={form.team_name}
                                        onChange={(e) =>
                                            handleIdentityChange("team_name", e.target.value)
                                        }
                                        placeholder="Outfitter Support Team"
                                        className="w-full bg-zinc-900 border border-zinc-800 rounded px-3 py-2 text-sm text-zinc-100 focus:border-zinc-600 focus:outline-none"
                                    />
                                </div>
                            </div>
                        </section>

                        {/* Card: Chat widget allowed origins */}
                        <section className="rounded border border-zinc-800 bg-zinc-950">
                            <div className="border-b border-zinc-800 px-5 py-3.5 bg-zinc-900/40">
                                <h2 className="text-sm font-semibold text-zinc-100">
                                    Chat Widget: Allowed Origins
                                </h2>
                                <p className="text-xs text-zinc-400">
                                    Websites that may embed this tenant&apos;s chat widget.
                                </p>
                            </div>
                            <div className="p-5">
                                <label
                                    htmlFor="allowed-origins"
                                    className="block text-xs font-medium text-zinc-300 mb-1.5"
                                >
                                    Allowed origins (one per line)
                                </label>
                                <textarea
                                    id="allowed-origins"
                                    rows={4}
                                    value={form.allowed_origins}
                                    onChange={(e) =>
                                        handleIdentityChange("allowed_origins", e.target.value)
                                    }
                                    placeholder="https://shop.example.com"
                                    spellCheck={false}
                                    className="w-full bg-zinc-900 border border-zinc-800 rounded px-3 py-2 font-mono text-xs text-zinc-100 focus:border-zinc-600 focus:outline-none"
                                />
                                <p className="text-xs text-zinc-500 mt-1.5">
                                    Exact origins only: scheme, host and optional port, such as
                                    https://shop.example.com. No wildcards or paths. A site that is
                                    not listed gets &quot;not allowed&quot; when its visitors open
                                    the chat. If this has never been set, the gateway&apos;s default
                                    list applies; saving an empty list allows no site at all.
                                </p>
                            </div>
                        </section>

                        {/* Card 2: AI Agent Configuration */}
                        <section className="rounded border border-zinc-800 bg-zinc-950">
                            <div className="border-b border-zinc-800 px-5 py-3.5 flex items-center justify-between bg-zinc-900/40">
                                <div>
                                    <h2 className="text-sm font-semibold text-zinc-100">
                                        AI Agent Configuration
                                    </h2>
                                    <p className="text-xs text-zinc-400">
                                        System prompt, tone, and Atlas $vectorSearch parameters.
                                    </p>
                                </div>
                                <span className="font-mono text-xs text-zinc-400">
                                    Llama-3.2-3B-Instruct
                                </span>
                            </div>

                            <div className="p-5 space-y-5">
                                {/* System Prompt Editor */}
                                <div>
                                    <div className="flex items-center justify-between mb-1.5">
                                        <label
                                            htmlFor="system-prompt"
                                            className="text-xs font-medium text-zinc-300"
                                        >
                                            System Prompt
                                        </label>
                                        <span className="font-mono text-xs text-zinc-500">
                                            {form.agent_config.system_prompt.length} chars
                                        </span>
                                    </div>
                                    <textarea
                                        id="system-prompt"
                                        rows={5}
                                        required
                                        value={form.agent_config.system_prompt}
                                        onChange={(e) =>
                                            handleAgentConfigChange(
                                                "system_prompt",
                                                e.target.value
                                            )
                                        }
                                        placeholder="You are a customer support agent for... Answer questions strictly using the provided context chunks."
                                        className="w-full bg-zinc-900 border border-zinc-800 rounded px-3 py-2 font-mono text-xs leading-relaxed text-zinc-100 focus:border-zinc-600 focus:outline-none"
                                    />
                                    <p className="mt-1 text-xs text-zinc-500">
                                        Prepended to retrieved context chunks during orchestration gateway prompt assembly.
                                    </p>
                                </div>

                                {/* Agent Tone Input + Quick-Select Preset Chips */}
                                <div>
                                    <label
                                        htmlFor="agent-tone"
                                        className="block text-xs font-medium text-zinc-300 mb-1.5"
                                    >
                                        Agent Tone
                                    </label>
                                    <input
                                        id="agent-tone"
                                        type="text"
                                        required
                                        value={form.agent_config.agent_tone}
                                        onChange={(e) =>
                                            handleAgentConfigChange("agent_tone", e.target.value)
                                        }
                                        placeholder="Warm & Professional"
                                        className="w-full bg-zinc-900 border border-zinc-800 rounded px-3 py-2 text-sm text-zinc-100 focus:border-zinc-600 focus:outline-none"
                                    />

                                    <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
                                        <span className="font-mono text-xs text-zinc-500 mr-1">
                                            presets:
                                        </span>
                                        {TONE_PRESETS.map((preset) => {
                                            const active =
                                                form.agent_config.agent_tone.toLowerCase() ===
                                                preset.toLowerCase();
                                            return (
                                                <button
                                                    key={preset}
                                                    type="button"
                                                    onClick={() =>
                                                        handleAgentConfigChange(
                                                            "agent_tone",
                                                            preset
                                                        )
                                                    }
                                                    className={`rounded px-2.5 py-1 text-xs cursor-pointer border ${
                                                        active
                                                            ? "bg-zinc-100 text-zinc-900 border-zinc-100 font-medium"
                                                            : "bg-zinc-900 text-zinc-300 border-zinc-800 hover:border-zinc-700"
                                                    }`}
                                                >
                                                    {preset}
                                                </button>
                                            );
                                        })}
                                    </div>
                                </div>

                                {/* Runtime Parameter Sliders */}
                                <div className="pt-1">
                                    <h3 className="text-xs font-medium text-zinc-300 mb-2.5">
                                        Runtime Parameters
                                    </h3>
                                    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                                        <ConfigSlider
                                            id="slider-temperature"
                                            label="Temperature"
                                            description="Sampling randomness (0.00–1.00)."
                                            value={form.agent_config.temperature}
                                            min={0.0}
                                            max={1.0}
                                            step={0.05}
                                            formatValue={(v) => v.toFixed(2)}
                                            minLabel="0.00"
                                            maxLabel="1.00"
                                            onChange={(val) =>
                                                handleAgentConfigChange("temperature", val)
                                            }
                                        />

                                        <ConfigSlider
                                            id="slider-max-chunks"
                                            label="Max Context Chunks"
                                            description="Top-K chunks retrieved per query."
                                            value={form.agent_config.max_context_chunks}
                                            min={1}
                                            max={8}
                                            step={1}
                                            formatValue={(v) => `${v}`}
                                            minLabel="1"
                                            maxLabel="8"
                                            onChange={(val) =>
                                                handleAgentConfigChange(
                                                    "max_context_chunks",
                                                    Math.round(val)
                                                )
                                            }
                                        />

                                        <ConfigSlider
                                            id="slider-similarity-threshold"
                                            label="Similarity Threshold"
                                            description="Minimum cosine similarity score."
                                            value={form.agent_config.similarity_threshold}
                                            min={0.5}
                                            max={0.95}
                                            step={0.01}
                                            formatValue={(v) => v.toFixed(2)}
                                            minLabel="0.50"
                                            maxLabel="0.95"
                                            onChange={(val) =>
                                                handleAgentConfigChange(
                                                    "similarity_threshold",
                                                    val
                                                )
                                            }
                                        />
                                    </div>
                                </div>
                            </div>

                            {/* Bottom Action Bar */}
                            <div className="border-t border-zinc-800 bg-zinc-900/40 px-5 py-3.5 flex items-center justify-between">
                                <div className="font-mono text-xs text-zinc-400">
                                    {hasUnsavedChanges ? (
                                        <span className="text-amber-400">
                                            status: unsaved_changes
                                        </span>
                                    ) : (
                                        <span>
                                            status: synced (businesses)
                                        </span>
                                    )}
                                </div>

                                <div className="flex items-center gap-2">
                                    <button
                                        type="button"
                                        onClick={handleReset}
                                        disabled={!hasUnsavedChanges || saving}
                                        className="rounded border border-zinc-800 bg-zinc-900 px-3 py-1.5 text-xs font-medium text-zinc-200 hover:bg-zinc-800 disabled:opacity-40 disabled:pointer-events-none cursor-pointer"
                                    >
                                        Discard Changes
                                    </button>
                                    <button
                                        type="submit"
                                        disabled={saving || !activeTenantId}
                                        className="rounded bg-zinc-100 hover:bg-white px-4 py-1.5 text-xs font-medium text-zinc-900 disabled:opacity-50 disabled:pointer-events-none cursor-pointer"
                                    >
                                        {saving ? "Saving..." : "Save Configuration"}
                                    </button>
                                </div>
                            </div>
                        </section>
                    </form>
                )}
            </main>
        </div>
    );
}
