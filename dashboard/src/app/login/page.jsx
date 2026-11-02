"use client";

import React, { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/context/AuthContext";

export default function LoginPage() {
    const router = useRouter();
    const {
        appMode,
        demoLoginEnabled,
        presetTenants,
        login,
        demoLogin,
    } = useAuth();

    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    const [submitting, setSubmitting] = useState(false);
    const [demoLoadingId, setDemoLoadingId] = useState("");
    const [error, setError] = useState(null);

    const handleStandardLogin = async (e) => {
        e.preventDefault();
        setError(null);
        setSubmitting(true);
        try {
            await login({ email: email.trim(), password });
            router.replace("/");
        } catch (err) {
            setError(err.message || "Invalid email or password.");
        } finally {
            setSubmitting(false);
        }
    };

    const handleDemoPresetLogin = async (tenantId) => {
        setError(null);
        setDemoLoadingId(tenantId);
        try {
            await demoLogin(tenantId);
            router.replace("/");
        } catch (err) {
            setError(err.message || "Failed to enter preset training session.");
        } finally {
            setDemoLoadingId("");
        }
    };

    const isPresetMode = appMode === "preset_training" && demoLoginEnabled;

    return (
        <div className="min-h-screen bg-zinc-950 text-zinc-100 flex flex-col justify-center items-center px-4 py-12">
            <div className="w-full max-w-md space-y-6">
                {/* Header */}
                <div className="space-y-1.5">
                    <div className="flex items-center justify-between">
                        <span className="font-mono text-xs uppercase tracking-wider text-zinc-400">
                            Support Admin Console
                        </span>
                        <span className="rounded border border-zinc-800 bg-zinc-900 px-2 py-0.5 font-mono text-[11px] text-zinc-300">
                            mode: {appMode}
                        </span>
                    </div>
                    <h1 className="text-xl font-semibold text-zinc-100">
                        {isPresetMode
                            ? "Preset Training Workspace"
                            : "Sign in to your workspace"}
                    </h1>
                    <p className="text-xs text-zinc-400">
                        {isPresetMode
                            ? "Select a synthetic training business below to launch a scoped demo session."
                            : "Enter your administrator credentials to manage your tenant knowledge base and runtime configuration."}
                    </p>
                </div>

                {error && (
                    <div
                        role="alert"
                        className="rounded border border-red-900 bg-red-950/60 p-3.5 text-xs text-red-200"
                    >
                        <p className="font-mono font-semibold uppercase text-[11px] text-red-300">
                            Authentication Error
                        </p>
                        <p className="mt-1">{error}</p>
                    </div>
                )}

                {/* Standard Email/Password Form (Shown in standard mode) */}
                {!isPresetMode && (
                    <div className="rounded border border-zinc-800 bg-zinc-900/30 p-6">
                        <form
                            onSubmit={handleStandardLogin}
                            className="space-y-4"
                        >
                            <div>
                                <label
                                    htmlFor="login-email"
                                    className="block text-xs font-medium text-zinc-300 mb-1.5"
                                >
                                    Work Email
                                </label>
                                <input
                                    id="login-email"
                                    type="email"
                                    required
                                    autoComplete="email"
                                    value={email}
                                    onChange={(e) => setEmail(e.target.value)}
                                    placeholder="admin@company.com"
                                    className="w-full bg-zinc-900 border border-zinc-800 rounded px-3 py-2 text-sm text-zinc-100 focus:border-zinc-600 focus:outline-none"
                                />
                            </div>

                            <div>
                                <label
                                    htmlFor="login-password"
                                    className="block text-xs font-medium text-zinc-300 mb-1.5"
                                >
                                    Password
                                </label>
                                <input
                                    id="login-password"
                                    type="password"
                                    required
                                    autoComplete="current-password"
                                    value={password}
                                    onChange={(e) =>
                                        setPassword(e.target.value)
                                    }
                                    placeholder="••••••••"
                                    className="w-full bg-zinc-900 border border-zinc-800 rounded px-3 py-2 text-sm text-zinc-100 focus:border-zinc-600 focus:outline-none"
                                />
                            </div>

                            <button
                                type="submit"
                                disabled={submitting}
                                className="w-full rounded bg-zinc-100 hover:bg-white px-4 py-2 text-xs font-medium text-zinc-900 disabled:opacity-50 cursor-pointer transition-colors"
                            >
                                {submitting ? "Signing in..." : "Sign In"}
                            </button>
                        </form>

                        <div className="mt-5 pt-4 border-t border-zinc-800/80 flex items-center justify-between text-xs">
                            <span className="text-zinc-400">
                                New business deployment?
                            </span>
                            <Link
                                href="/signup"
                                className="font-medium text-zinc-200 hover:text-white underline underline-offset-4"
                            >
                                Complete onboarding &rarr;
                            </Link>
                        </div>
                    </div>
                )}

                {/* Quick Demo Login Buttons (Shown ONLY when server APP_MODE=preset_training) */}
                {isPresetMode && (
                    <div className="rounded border border-zinc-800 bg-zinc-900/30 p-5 space-y-3">
                        <div className="flex items-center justify-between">
                            <span className="font-mono text-xs uppercase text-zinc-300">
                                Quick Demo Login (No Password)
                            </span>
                            <span className="font-mono text-[11px] text-amber-400">
                                synthetic fixtures
                            </span>
                        </div>

                        <div className="space-y-2">
                            {presetTenants.map((preset) => {
                                const isCurrentLoading =
                                    demoLoadingId === preset.tenant_id;
                                return (
                                    <button
                                        key={preset.tenant_id}
                                        type="button"
                                        disabled={Boolean(demoLoadingId)}
                                        onClick={() =>
                                            handleDemoPresetLogin(
                                                preset.tenant_id
                                            )
                                        }
                                        className="w-full text-left rounded border border-zinc-800 bg-zinc-900 hover:bg-zinc-800/80 hover:border-zinc-700 p-3 transition-colors flex items-center justify-between gap-3 disabled:opacity-50 cursor-pointer"
                                    >
                                        <div className="min-w-0">
                                            <p className="text-sm font-medium text-zinc-100 truncate">
                                                {preset.name}
                                            </p>
                                            <p className="text-xs text-zinc-400 truncate mt-0.5">
                                                {preset.industry}
                                            </p>
                                        </div>
                                        <div className="shrink-0 flex items-center gap-2">
                                            <span className="rounded bg-zinc-950 border border-zinc-800 px-2 py-0.5 font-mono text-xs text-zinc-300">
                                                {isCurrentLoading
                                                    ? "entering..."
                                                    : preset.tenant_id}
                                            </span>
                                        </div>
                                    </button>
                                );
                            })}
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}

