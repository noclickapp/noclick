// Chart palette and color-assignment rules shared by the usage dashboard and
// drawer. Centralizes two fixes: resource-type colors are KEYED (the bar chart
// previously mapped them by sort position, so "AI purple" landed on whatever
// type spent the most), and model/series colors are assigned by stable hash so
// a model keeps its color across date ranges and across the bar/pie views.

import type React from 'react';
import { defaultStyles } from '@visx/tooltip';

/* Theme-reactive: SVG fills/strokes accept CSS var() colors, so these follow
   the .dark class live. Dark stays pixel-exact — --usage-chart-bg pins the
   original zinc-950 panel, foreground/border match the old zinc-50/zinc-800. */
export const CHART_THEME = {
    background: 'hsl(var(--usage-chart-bg))',
    text: 'hsl(var(--foreground))',
    textMuted: 'hsl(var(--muted-foreground) / 0.75)',
    border: 'hsl(var(--border))',
    gridStroke: 'hsl(var(--border))',
} as const;

/** Fixed semantic colors for the high-level usage_type categories. Keyed —
 * never map these positionally onto a sorted key list. */
export const RESOURCE_TYPE_COLORS: Record<string, string> = {
    ai_usage: '#a44afe', // purple
    ai_builder: '#f59e0b', // amber, matches the AI Builder badge accent
    ai_testing: '#14b8a6', // teal — the rehearsal world-model (Agent Testing)
    cpu_usage: '#6c5efb', // blue-purple
    gpu_usage: '#c998ff', // light purple
    api_usage: '#1d9bf0', // blue
};

// Extended palette for models/services — diverse hues to avoid repetition.
export const MODEL_COLORS = [
    '#a44afe', // Purple
    '#6c5efb', // Blue-purple
    '#3b82f6', // Blue
    '#10b981', // Green
    '#f59e0b', // Orange
    '#ef4444', // Red
    '#ec4899', // Pink
    '#8b5cf6', // Violet
    '#06b6d4', // Cyan
    '#84cc16', // Lime
    '#f97316', // Deep orange
    '#14b8a6', // Teal
    '#a78bfa', // Light purple
    '#fbbf24', // Yellow
    '#fb923c', // Light orange
    '#c4b5fd', // Very light purple
];

function hashSlot(key: string, mod: number): number {
    let h = 0;
    for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) | 0;
    return Math.abs(h) % mod;
}

/** Stable single-key color (hash into the palette). Used as the fallback for
 * usage_type keys missing from RESOURCE_TYPE_COLORS. */
export function hashColor(key: string): string {
    return MODEL_COLORS[hashSlot(key, MODEL_COLORS.length)];
}

export function colorForUsageType(key: string): string {
    return RESOURCE_TYPE_COLORS[key] ?? hashColor(key);
}

/**
 * Deterministic color per series key. Each key prefers its hash slot, then
 * linear-probes to a free one — so colors are stable for a given key set AND
 * unique within a chart while the palette has capacity (≤16 series). Keys are
 * assigned in sorted order so the result doesn't depend on how the caller
 * ordered them (bar sorts by cost, pie by value — both get identical colors).
 */
export function assignSeriesColors(keys: string[]): Record<string, string> {
    const n = MODEL_COLORS.length;
    const used = new Set<number>();
    const out: Record<string, string> = {};
    for (const key of [...keys].sort()) {
        let slot = hashSlot(key, n);
        if (used.size < n) {
            while (used.has(slot)) slot = (slot + 1) % n;
        }
        used.add(slot);
        out[key] = MODEL_COLORS[slot];
    }
    return out;
}

function hexToRgb(hex: string): { r: number; g: number; b: number } {
    const n = parseInt(hex.slice(1), 16);
    return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 };
}

/**
 * Category chip style derived from the SAME hex the charts use, so a badge
 * always matches its bar/pie color exactly: 15% tint background, text mixed
 * 45% toward --usage-badge-mix (white in dark — identical math to the old
 * lift-toward-white; black in light) for legibility on either surface.
 * Unknown categories get a neutral chip.
 */
export function usageTypeBadgeStyle(usageType?: string): React.CSSProperties {
    const hex = usageType ? RESOURCE_TYPE_COLORS[usageType] : undefined;
    if (!hex) {
        return {
            backgroundColor: 'hsl(var(--foreground) / 0.06)',
            color: 'hsl(var(--foreground) / 0.5)',
        };
    }
    const { r, g, b } = hexToRgb(hex);
    return {
        backgroundColor: `rgba(${r}, ${g}, ${b}, 0.15)`,
        color: `color-mix(in srgb, ${hex} 55%, var(--usage-badge-mix))`,
    };
}

/** visx tooltip base style shared by every usage chart. Spreads visx
 * defaultStyles first for the positioning/pointer-events baseline. */
export const USAGE_TOOLTIP_STYLES: React.CSSProperties = {
    ...defaultStyles,
    minWidth: 120,
    backgroundColor: 'hsl(var(--usage-chart-bg) / 0.95)',
    color: 'hsl(var(--foreground))',
    border: '1px solid hsl(var(--border))',
    borderRadius: '8px',
    padding: '12px',
    fontSize: '12px',
};
