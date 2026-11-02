"use client";

import React from "react";

export default function MetricCard({
    label,
    value,
    badge,
    subtext,
    monoValue = false,
}) {
    return (
        <div className="rounded border border-zinc-800 bg-zinc-900/40 p-4 flex flex-col justify-between">
            <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-medium text-zinc-400">
                    {label}
                </span>
                {badge && (
                    <span className="rounded bg-zinc-900 border border-zinc-800 px-1.5 py-0.5 font-mono text-[11px] text-zinc-300">
                        {badge}
                    </span>
                )}
            </div>

            <div className="mt-2">
                <div
                    className={
                        monoValue
                            ? "font-mono text-sm font-semibold text-zinc-100 truncate"
                            : "text-xl font-semibold text-zinc-100 tracking-tight truncate"
                    }
                    title={String(value ?? "")}
                >
                    {value}
                </div>
                {subtext && (
                    <div className="mt-1 font-mono text-xs text-zinc-500 truncate">
                        {subtext}
                    </div>
                )}
            </div>
        </div>
    );
}

