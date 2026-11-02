"use client";

import React, { useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { clsx } from "clsx";
import { twMerge } from "tailwind-merge";
import {
    LayoutDashboard,
    Inbox,
    Sliders,
    ChevronDown,
    RefreshCw,
    Menu,
    X,
} from "lucide-react";
import { useTenant } from "@/context/TenantContext";
import { useAuth } from "@/context/AuthContext";

function cn(...inputs) {
    return twMerge(clsx(inputs));
}

const NAV_ITEMS = [
    {
        name: "Overview",
        href: "/",
        icon: LayoutDashboard,
    },
    {
        name: "Ticket Queue",
        href: "/tickets",
        icon: Inbox,
    },
    {
        name: "Profile & Config",
        href: "/profile",
        icon: Sliders,
    },
];

export default function Sidebar() {
    const pathname = usePathname();
    const router = useRouter();
    const {
        user,
        appMode,
        demoLoginEnabled,
        presetTenants,
        logout,
    } = useAuth();
    const {
        tenants,
        activeTenantId,
        activeTenant,
        setActiveTenantId,
        refreshTenants,
        loading,
        error,
    } = useTenant();
    const [mobileOpen, setMobileOpen] = useState(false);
    const [loggingOut, setLoggingOut] = useState(false);

    const isDemoSelectorMode =
        appMode === "preset_training" &&
        demoLoginEnabled &&
        presetTenants.length > 0;
    const selectableTenants = isDemoSelectorMode ? presetTenants : tenants;

    const handleLogout = async () => {
        setLoggingOut(true);
        try {
            await logout();
            router.replace("/login");
        } finally {
            setLoggingOut(false);
        }
    };

    return (
        <>
            {/* Mobile Top Header */}
            <div className="lg:hidden flex items-center justify-between px-4 py-3 bg-zinc-950 border-b border-zinc-800 text-zinc-100 sticky top-0 z-40">
                <div className="flex items-center gap-2">
                    <span className="font-semibold text-sm text-zinc-100">
                        Admin Console
                    </span>
                    <span className="font-mono text-xs text-zinc-400">
                        [{activeTenantId || "loading"}]
                    </span>
                </div>
                <button
                    type="button"
                    onClick={() => setMobileOpen(!mobileOpen)}
                    className="p-1.5 rounded border border-zinc-800 text-zinc-300 hover:text-zinc-100 hover:bg-zinc-900"
                    aria-label="Toggle navigation menu"
                >
                    {mobileOpen ? (
                        <X className="h-4 w-4" />
                    ) : (
                        <Menu className="h-4 w-4" />
                    )}
                </button>
            </div>

            {/* Mobile Overlay */}
            {mobileOpen && (
                <div
                    className="fixed inset-0 bg-black/70 z-40 lg:hidden"
                    onClick={() => setMobileOpen(false)}
                />
            )}

            {/* Sidebar Container */}
            <aside
                className={cn(
                    "fixed inset-y-0 left-0 z-50 w-64 bg-zinc-950 text-zinc-200 border-r border-zinc-800 flex flex-col lg:static lg:translate-x-0 lg:shrink-0",
                    mobileOpen ? "translate-x-0" : "-translate-x-full"
                )}
            >
                {/* Header */}
                <div className="px-4 py-4 border-b border-zinc-800">
                    <div className="flex items-center justify-between gap-2">
                        <h1 className="font-semibold text-sm text-zinc-100">
                            Support Admin Console
                        </h1>
                        <span
                            className={cn(
                                "rounded border px-1.5 py-0.5 font-mono text-[10px]",
                                appMode === "preset_training"
                                    ? "bg-amber-950/50 border-amber-800 text-amber-300"
                                    : "bg-zinc-900 border-zinc-800 text-zinc-400"
                            )}
                        >
                            {appMode}
                        </span>
                    </div>
                    <p className="font-mono text-xs text-zinc-500 mt-0.5">
                        Multi-Tenant RAG Gateway
                    </p>
                </div>

                {/* Authorized Tenant Selector */}
                <div className="p-4 border-b border-zinc-800">
                    <div className="flex items-center justify-between mb-1.5">
                        {isDemoSelectorMode ? (
                            <label
                                htmlFor="sidebar-tenant-selector"
                                className="text-xs font-medium text-zinc-400"
                            >
                                Preset Demo Tenant
                            </label>
                        ) : (
                            <span className="text-xs font-medium text-zinc-400">
                                Authorized Workspace
                            </span>
                        )}
                        <button
                            type="button"
                            onClick={refreshTenants}
                            title="Refresh authorized workspace from Gateway"
                            className="text-zinc-400 hover:text-zinc-200 p-1 rounded cursor-pointer"
                        >
                            <RefreshCw
                                className={cn(
                                    "h-3.5 w-3.5",
                                    loading && "animate-spin"
                                )}
                            />
                        </button>
                    </div>

                    {isDemoSelectorMode ? (
                        <div className="relative">
                            <select
                                id="sidebar-tenant-selector"
                                value={activeTenantId}
                                onChange={(e) => setActiveTenantId(e.target.value)}
                                disabled={
                                    loading || selectableTenants.length === 0
                                }
                                className="w-full appearance-none bg-zinc-900 border border-zinc-800 rounded px-3 py-2 pr-8 text-sm text-zinc-100 focus:border-zinc-600 focus:outline-none disabled:opacity-60 cursor-pointer"
                            >
                                {loading && selectableTenants.length === 0 ? (
                                    <option value="">Loading workspace...</option>
                                ) : selectableTenants.length === 0 ? (
                                    <option value="">No tenants available</option>
                                ) : (
                                    selectableTenants.map((tenant) => (
                                        <option
                                            key={tenant.tenant_id}
                                            value={tenant.tenant_id}
                                        >
                                            {tenant.name}
                                        </option>
                                    ))
                                )}
                            </select>
                            <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-zinc-400" />
                        </div>
                    ) : (
                        <div className="w-full bg-zinc-900 border border-zinc-800 rounded px-3 py-2 text-sm text-zinc-100 truncate">
                            {loading && !activeTenant ? (
                                <span className="text-zinc-400">
                                    Loading workspace...
                                </span>
                            ) : (
                                activeTenant?.name ||
                                user?.tenant_id ||
                                "No workspace loaded"
                            )}
                        </div>
                    )}

                    {activeTenant && (
                        <div className="mt-2 flex items-center justify-between text-xs">
                            <span
                                className="text-zinc-500 truncate max-w-[115px]"
                                title={activeTenant.industry}
                            >
                                {activeTenant.industry || "Configured"}
                            </span>
                            <span className="font-mono text-xs text-zinc-300 bg-zinc-900 border border-zinc-800 rounded px-1.5 py-0.5">
                                {activeTenant.tenant_id}
                            </span>
                        </div>
                    )}

                    {error && (
                        <div className="mt-2 rounded bg-red-950/60 border border-red-900 px-2.5 py-1.5 text-xs text-red-200">
                            {error}
                        </div>
                    )}
                </div>

                {/* Primary Navigation Links */}
                <nav className="flex-1 px-3 py-3 space-y-1 overflow-y-auto">
                    {NAV_ITEMS.map((item) => {
                        const Icon = item.icon;
                        const isActive =
                            item.href === "/"
                                ? pathname === "/"
                                : pathname?.startsWith(item.href);

                        return (
                            <Link
                                key={item.href}
                                href={item.href}
                                onClick={() => setMobileOpen(false)}
                                className={cn(
                                    "flex items-center gap-2.5 rounded px-3 py-2 text-sm transition-colors",
                                    isActive
                                        ? "bg-zinc-900 text-zinc-100 font-medium border border-zinc-800"
                                        : "text-zinc-400 hover:bg-zinc-900/60 hover:text-zinc-200 border border-transparent"
                                )}
                            >
                                <Icon className="h-4 w-4 shrink-0" />
                                <span className="truncate">{item.name}</span>
                            </Link>
                        );
                    })}
                </nav>

                {/* Authenticated Principal & Sign Out Footer */}
                <div className="p-4 border-t border-zinc-800 space-y-3">
                    {user && (
                        <div className="rounded border border-zinc-800 bg-zinc-900/40 px-3 py-2">
                            <p className="text-xs font-medium text-zinc-200 truncate">
                                {user.name}
                            </p>
                            <p className="font-mono text-[11px] text-zinc-400 truncate mt-0.5">
                                {user.email || `principal: ${user.principal_type}`}
                            </p>
                        </div>
                    )}

                    <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-2 font-mono text-xs text-zinc-400">
                            <span
                                className={cn(
                                    "h-2 w-2 rounded-full shrink-0",
                                    error
                                        ? "bg-red-500"
                                        : loading
                                        ? "bg-amber-400"
                                        : "bg-emerald-500"
                                )}
                            />
                            <span className="truncate">
                                {error ? "gateway: err" : "gateway: :4000"}
                            </span>
                        </div>

                        <button
                            type="button"
                            onClick={handleLogout}
                            disabled={loggingOut}
                            className="rounded border border-zinc-800 bg-zinc-900 hover:bg-zinc-800 px-2.5 py-1 font-mono text-xs text-zinc-300 hover:text-zinc-100 disabled:opacity-50 cursor-pointer"
                        >
                            {loggingOut ? "Signing out..." : "Sign Out"}
                        </button>
                    </div>
                </div>
            </aside>
        </>
    );
}
