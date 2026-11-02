"use client";

import React, { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/context/AuthContext";
import Sidebar from "@/components/Sidebar";

export default function AppShell({ children }) {
    const pathname = usePathname();
    const router = useRouter();
    const { authenticated, loading } = useAuth();

    const isPublicAuthRoute =
        pathname === "/login" || pathname === "/signup";

    useEffect(() => {
        if (loading) return;
        if (!authenticated && !isPublicAuthRoute) {
            router.replace("/login");
        } else if (authenticated && isPublicAuthRoute) {
            router.replace("/");
        }
    }, [loading, authenticated, isPublicAuthRoute, router]);

    // Public auth routes (/login, /signup) render their segment directly when not authenticated
    if (isPublicAuthRoute) {
        if (!loading && authenticated) {
            return (
                <div className="min-h-screen bg-zinc-950 text-zinc-100 flex items-center justify-center p-6">
                    <div className="rounded border border-zinc-800 bg-zinc-900/40 px-6 py-4 text-center">
                        <p className="font-mono text-xs text-zinc-400">
                            Session verified. Loading workspace...
                        </p>
                    </div>
                </div>
            );
        }
        return <div className="min-h-screen bg-zinc-950">{children}</div>;
    }

    if (loading) {
        return (
            <div className="min-h-screen bg-zinc-950 text-zinc-100 flex items-center justify-center p-6">
                <div className="rounded border border-zinc-800 bg-zinc-900/40 px-6 py-4 text-center">
                    <p className="font-mono text-xs text-zinc-300">
                        Verifying session with Orchestration Gateway...
                    </p>
                </div>
            </div>
        );
    }

    if (!authenticated) {
        return (
            <div className="min-h-screen bg-zinc-950 text-zinc-100 flex items-center justify-center p-6">
                <div className="rounded border border-zinc-800 bg-zinc-900/40 px-6 py-4 text-center">
                    <p className="font-mono text-xs text-zinc-400">
                        Redirecting to authentication...
                    </p>
                </div>
            </div>
        );
    }

    return (
        <div className="min-h-screen flex flex-col lg:flex-row">
            <Sidebar />
            <div className="flex-1 flex flex-col min-w-0">{children}</div>
        </div>
    );
}
