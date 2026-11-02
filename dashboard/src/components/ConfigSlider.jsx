"use client";

import React from "react";

export default function ConfigSlider({
    id,
    label,
    description,
    value,
    min,
    max,
    step,
    onChange,
    formatValue,
    minLabel,
    maxLabel,
    unit = "",
}) {
    const numericValue = Number(value ?? min);
    const displayValue = formatValue
        ? formatValue(numericValue)
        : `${numericValue}${unit}`;

    return (
        <div className="rounded border border-zinc-800 bg-zinc-900/40 p-4">
            <div className="flex items-start justify-between gap-4 mb-2">
                <div>
                    <label
                        htmlFor={id}
                        className="text-sm font-medium text-zinc-100 block"
                    >
                        {label}
                    </label>
                    {description && (
                        <p className="text-xs text-zinc-400 mt-0.5">
                            {description}
                        </p>
                    )}
                </div>
                <span className="inline-flex items-center rounded bg-zinc-900 border border-zinc-800 px-2 py-0.5 font-mono text-xs text-zinc-200 shrink-0">
                    {displayValue}
                </span>
            </div>

            <div className="mt-3">
                <input
                    id={id}
                    type="range"
                    min={min}
                    max={max}
                    step={step}
                    value={numericValue}
                    onChange={(e) => onChange(Number(e.target.value))}
                    className="w-full h-1.5 bg-zinc-800 rounded appearance-none cursor-pointer accent-zinc-200 focus:outline-none"
                />
                <div className="flex justify-between font-mono text-xs text-zinc-500 mt-1.5">
                    <span>{minLabel || min}</span>
                    <span>{maxLabel || max}</span>
                </div>
            </div>
        </div>
    );
}
