"use client";

import React, { useState, useMemo } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/context/AuthContext";

const TONE_PRESETS = [
    "Warm & Professional",
    "Rugged & Direct",
    "Empathetic & Clinical",
    "Technical & Concise",
    "Friendly & Conversational",
];

function previewSlug(businessName) {
    if (!businessName) return "your_business_id";
    const slug = businessName
        .trim()
        .toLowerCase()
        .replace(/&/g, " and ")
        .replace(/[^a-z0-9]+/g, "_")
        .replace(/^_+|_+$/g, "")
        .replace(/_+/g, "_")
        .slice(0, 48);
    return slug.length >= 2 ? slug : "your_business_id";
}

function buildGeneratedPrompt({ businessName, industry, contactEmail }) {
    const cleanName = (businessName || "your business").trim();
    const cleanIndustry = (industry || "").trim();
    const cleanEmail = (contactEmail || "").trim();
    const sectorPhrase = cleanIndustry ? ` (${cleanIndustry})` : "";
    const escalationPhrase = cleanEmail
        ? ` If the answer is not verified by the provided context, state that clearly and offer to escalate the inquiry to ${cleanEmail}.`
        : " If the answer is not verified by the provided context, state that clearly and offer to escalate the inquiry to a human support specialist.";

    return `You are a customer support agent for ${cleanName}${sectorPhrase}. Answer customer questions strictly using the provided context chunks.${escalationPhrase}`;
}

export default function SignupOnboardingPage() {
    const router = useRouter();
    const { appMode, signup } = useAuth();

    const [adminName, setAdminName] = useState("");
    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");

    const [businessName, setBusinessName] = useState("");
    const [industry, setIndustry] = useState("");
    const [contactEmail, setContactEmail] = useState("");
    const [agentTone, setAgentTone] = useState("Warm & Professional");
    const [customPrompt, setCustomPrompt] = useState("");
    const [useCustomPrompt, setUseCustomPrompt] = useState(false);

    const [submitting, setSubmitting] = useState(false);
    const [error, setError] = useState(null);

    const proposedTenantId = useMemo(
        () => previewSlug(businessName),
        [businessName]
    );

    const effectiveSupportEmail = (contactEmail || email).trim();

    const autoSystemPrompt = useMemo(
        () =>
            buildGeneratedPrompt({
                businessName,
                industry,
                contactEmail: effectiveSupportEmail,
            }),
        [businessName, industry, effectiveSupportEmail]
    );

    const handleSignupSubmit = async (e) => {
        e.preventDefault();
        setError(null);
        setSubmitting(true);
        try {
            await signup({
                admin_name: adminName.trim(),
                email: email.trim().toLowerCase(),
                password,
                business_name: businessName.trim(),
                industry: industry.trim(),
                contact_email: effectiveSupportEmail.toLowerCase(),
                agent_tone: agentTone,
                system_prompt: useCustomPrompt
                    ? customPrompt.trim()
                    : autoSystemPrompt,
            });
            router.replace("/");
        } catch (err) {
            setError(err.message || "Failed to complete onboarding.");
        } finally {
            setSubmitting(false);
        }
    };

    if (appMode === "preset_training") {
        return (
            <div className="min-h-screen bg-zinc-950 text-zinc-100 flex flex-col justify-center items-center px-4 py-12">
                <div className="w-full max-w-md rounded border border-zinc-800 bg-zinc-900/30 p-6 space-y-4">
                    <h1 className="text-lg font-semibold text-zinc-100">
                        Preset Training Mode Active
                    </h1>
                    <p className="text-xs text-zinc-400 leading-relaxed">
                        Standard tenant registration is disabled while the
                        server is running in{" "}
                        <code className="font-mono text-zinc-200">
                            preset_training
                        </code>{" "}
                        mode. Use the one-click preset demo login instead.
                    </p>
                    <Link
                        href="/login"
                        className="inline-block rounded bg-zinc-100 hover:bg-white px-4 py-2 text-xs font-medium text-zinc-900"
                    >
                        Return to Preset Demo Login
                    </Link>
                </div>
            </div>
        );
    }

    return (
        <div className="min-h-screen bg-zinc-950 text-zinc-100 py-10 px-4 flex justify-center">
            <div className="w-full max-w-3xl space-y-6">
                {/* Top Header */}
                <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 border-b border-zinc-800 pb-4">
                    <div>
                        <span className="font-mono text-xs uppercase tracking-wider text-zinc-400">
                            Workspace Onboarding
                        </span>
                        <h1 className="text-xl font-semibold text-zinc-100 mt-0.5">
                            Create Administrator Account &amp; Tenant Profile
                        </h1>
                        <p className="text-xs text-zinc-400 mt-1">
                            Configure your business identity and initial grounded
                            RAG system prompt.
                        </p>
                    </div>
                    <Link
                        href="/login"
                        className="rounded border border-zinc-800 bg-zinc-900 hover:bg-zinc-800 px-3 py-1.5 text-xs text-zinc-300 self-start sm:self-auto"
                    >
                        Existing account? Sign in
                    </Link>
                </div>

                {error && (
                    <div
                        role="alert"
                        className="rounded border border-red-900 bg-red-950/60 p-4 text-xs text-red-200"
                    >
                        <p className="font-mono font-semibold uppercase text-[11px] text-red-300">
                            Registration Error
                        </p>
                        <p className="mt-1">{error}</p>
                    </div>
                )}

                <form onSubmit={handleSignupSubmit} className="space-y-6">
                    {/* Step 1: Administrator Credentials */}
                    <section className="rounded border border-zinc-800 bg-zinc-900/30 p-5 space-y-4">
                        <div className="border-b border-zinc-800/80 pb-2.5 flex items-center justify-between">
                            <h2 className="text-sm font-semibold text-zinc-100">
                                1. Administrator Credentials
                            </h2>
                            <span className="font-mono text-xs text-zinc-500">
                                admin_users
                            </span>
                        </div>

                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                            <div>
                                <label
                                    htmlFor="signup-admin-name"
                                    className="block text-xs font-medium text-zinc-300 mb-1.5"
                                >
                                    Admin / Team Lead Name
                                </label>
                                <input
                                    id="signup-admin-name"
                                    type="text"
                                    required
                                    minLength={2}
                                    value={adminName}
                                    onChange={(e) =>
                                        setAdminName(e.target.value)
                                    }
                                    placeholder="Alex Rivera"
                                    className="w-full bg-zinc-900 border border-zinc-800 rounded px-3 py-2 text-sm text-zinc-100 focus:border-zinc-600 focus:outline-none"
                                />
                            </div>

                            <div>
                                <label
                                    htmlFor="signup-email"
                                    className="block text-xs font-medium text-zinc-300 mb-1.5"
                                >
                                    Work Email (Login ID)
                                </label>
                                <input
                                    id="signup-email"
                                    type="email"
                                    required
                                    autoComplete="email"
                                    value={email}
                                    onChange={(e) => setEmail(e.target.value)}
                                    placeholder="alex@company.com"
                                    className="w-full bg-zinc-900 border border-zinc-800 rounded px-3 py-2 text-sm text-zinc-100 focus:border-zinc-600 focus:outline-none"
                                />
                            </div>

                            <div className="sm:col-span-2">
                                <label
                                    htmlFor="signup-password"
                                    className="block text-xs font-medium text-zinc-300 mb-1.5"
                                >
                                    Password (minimum 8 characters)
                                </label>
                                <input
                                    id="signup-password"
                                    type="password"
                                    required
                                    minLength={8}
                                    autoComplete="new-password"
                                    value={password}
                                    onChange={(e) =>
                                        setPassword(e.target.value)
                                    }
                                    placeholder="••••••••••••"
                                    className="w-full bg-zinc-900 border border-zinc-800 rounded px-3 py-2 text-sm text-zinc-100 focus:border-zinc-600 focus:outline-none"
                                />
                            </div>
                        </div>
                    </section>

                    {/* Step 2: Business Identity ("Get to Know You") */}
                    <section className="rounded border border-zinc-800 bg-zinc-900/30 p-5 space-y-4">
                        <div className="border-b border-zinc-800/80 pb-2.5 flex items-center justify-between">
                            <h2 className="text-sm font-semibold text-zinc-100">
                                2. Get to Know Your Business
                            </h2>
                            <span className="font-mono text-xs text-zinc-500">
                                businesses
                            </span>
                        </div>

                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                            <div>
                                <label
                                    htmlFor="signup-business-name"
                                    className="block text-xs font-medium text-zinc-300 mb-1.5"
                                >
                                    Business Name
                                </label>
                                <input
                                    id="signup-business-name"
                                    type="text"
                                    required
                                    minLength={2}
                                    value={businessName}
                                    onChange={(e) =>
                                        setBusinessName(e.target.value)
                                    }
                                    placeholder="Cascade Bicycle Works"
                                    className="w-full bg-zinc-900 border border-zinc-800 rounded px-3 py-2 text-sm text-zinc-100 focus:border-zinc-600 focus:outline-none"
                                />
                            </div>

                            <div>
                                <label
                                    htmlFor="signup-industry"
                                    className="block text-xs font-medium text-zinc-300 mb-1.5"
                                >
                                    Sector / Industry
                                </label>
                                <input
                                    id="signup-industry"
                                    type="text"
                                    required
                                    minLength={2}
                                    value={industry}
                                    onChange={(e) =>
                                        setIndustry(e.target.value)
                                    }
                                    placeholder="Retail & Custom Bike Repair"
                                    className="w-full bg-zinc-900 border border-zinc-800 rounded px-3 py-2 text-sm text-zinc-100 focus:border-zinc-600 focus:outline-none"
                                />
                            </div>

                            <div className="sm:col-span-2">
                                <label
                                    htmlFor="signup-contact-email"
                                    className="block text-xs font-medium text-zinc-300 mb-1.5"
                                >
                                    Customer Support Escalation Email
                                </label>
                                <input
                                    id="signup-contact-email"
                                    type="email"
                                    required
                                    value={contactEmail}
                                    onChange={(e) =>
                                        setContactEmail(e.target.value)
                                    }
                                    placeholder={
                                        email || "support@company.com"
                                    }
                                    className="w-full bg-zinc-900 border border-zinc-800 rounded px-3 py-2 text-sm text-zinc-100 focus:border-zinc-600 focus:outline-none"
                                />
                            </div>

                            <div className="sm:col-span-2">
                                <span className="block text-xs font-medium text-zinc-300 mb-2">
                                    Agent Voice &amp; Tone
                                </span>
                                <div className="flex flex-wrap gap-2">
                                    {TONE_PRESETS.map((tone) => {
                                        const selected = agentTone === tone;
                                        return (
                                            <button
                                                key={tone}
                                                type="button"
                                                onClick={() =>
                                                    setAgentTone(tone)
                                                }
                                                className={`rounded border px-3 py-1.5 text-xs font-medium transition-colors cursor-pointer ${
                                                    selected
                                                        ? "bg-zinc-100 text-zinc-900 border-zinc-100"
                                                        : "bg-zinc-900 text-zinc-300 border-zinc-800 hover:border-zinc-700"
                                                }`}
                                            >
                                                {tone}
                                            </button>
                                        );
                                    })}
                                </div>
                            </div>
                        </div>
                    </section>

                    {/* Step 3: Live Tenant ID & System Prompt Preview */}
                    <section className="rounded border border-zinc-800 bg-zinc-900/30 p-5 space-y-4">
                        <div className="border-b border-zinc-800/80 pb-2.5 flex flex-wrap items-center justify-between gap-2">
                            <div>
                                <h2 className="text-sm font-semibold text-zinc-100">
                                    3. Proposed Tenant Namespace &amp; Grounded
                                    Prompt Preview
                                </h2>
                                <p className="text-xs text-zinc-400 mt-0.5">
                                    The Gateway enforces final{" "}
                                    <code className="font-mono">tenant_id</code>{" "}
                                    uniqueness upon registration.
                                </p>
                            </div>
                            <span className="rounded bg-zinc-900 border border-zinc-800 px-2.5 py-1 font-mono text-xs text-zinc-200">
                                proposed tenant_id: {proposedTenantId}
                            </span>
                        </div>

                        <div>
                            <div className="flex items-center justify-between mb-1.5">
                                <label
                                    htmlFor="signup-system-prompt"
                                    className="font-mono text-xs uppercase text-zinc-400"
                                >
                                    agent_config.system_prompt
                                </label>
                                <button
                                    type="button"
                                    onClick={() => {
                                        if (!useCustomPrompt) {
                                            setCustomPrompt(autoSystemPrompt);
                                            setUseCustomPrompt(true);
                                        } else {
                                            setUseCustomPrompt(false);
                                        }
                                    }}
                                    className="font-mono text-xs text-zinc-300 hover:text-white underline cursor-pointer"
                                >
                                    {useCustomPrompt
                                        ? "Reset to auto-generated prompt"
                                        : "Customize prompt"}
                                </button>
                            </div>

                            {useCustomPrompt ? (
                                <textarea
                                    id="signup-system-prompt"
                                    rows={3}
                                    value={customPrompt}
                                    onChange={(e) =>
                                        setCustomPrompt(e.target.value)
                                    }
                                    className="w-full rounded border border-zinc-800 bg-zinc-900 p-3 font-mono text-xs text-zinc-100 focus:border-zinc-600 focus:outline-none"
                                />
                            ) : (
                                <pre className="whitespace-pre-wrap break-words rounded border border-zinc-800 bg-zinc-950 p-3.5 font-mono text-xs text-zinc-200 leading-relaxed">
                                    {autoSystemPrompt}
                                </pre>
                            )}
                        </div>

                        <div className="grid grid-cols-3 gap-3 pt-1 font-mono text-xs">
                            <div className="rounded border border-zinc-800 bg-zinc-950 px-3 py-2">
                                <span className="text-zinc-500 block text-[11px]">
                                    temperature
                                </span>
                                <span className="text-zinc-200">0.20</span>
                            </div>
                            <div className="rounded border border-zinc-800 bg-zinc-950 px-3 py-2">
                                <span className="text-zinc-500 block text-[11px]">
                                    max_context_chunks
                                </span>
                                <span className="text-zinc-200">4</span>
                            </div>
                            <div className="rounded border border-zinc-800 bg-zinc-950 px-3 py-2">
                                <span className="text-zinc-500 block text-[11px]">
                                    similarity_threshold
                                </span>
                                <span className="text-zinc-200">0.70</span>
                            </div>
                        </div>
                    </section>

                    <div className="flex items-center justify-end gap-3">
                        <Link
                            href="/login"
                            className="rounded border border-zinc-800 bg-zinc-900 hover:bg-zinc-800 px-4 py-2 text-xs font-medium text-zinc-300"
                        >
                            Cancel
                        </Link>
                        <button
                            type="submit"
                            disabled={submitting}
                            className="rounded bg-zinc-100 hover:bg-white px-5 py-2 text-xs font-medium text-zinc-900 disabled:opacity-50 cursor-pointer transition-colors"
                        >
                            {submitting
                                ? "Provisioning Workspace..."
                                : "Complete Onboarding & Launch Console"}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
}

