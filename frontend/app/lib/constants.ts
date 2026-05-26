// UI Constants for the NoClick application
// Centralizes common UI values to ensure consistency across components

// Default panel width as a percentage of viewport width
export const DEFAULT_PANEL_WIDTH_VW = 30;

// Sidebar default width is `vwToPixels(30) * scale` where `scale` matches
// the root-font-size tier in tailwind.css. Mirrors those media queries:
//   mobile (<=768)    → 1.0   (mobile has its own layout, no shrinking)
//   1152 < w <= 1366  → 0.85
//   768  < w <= 1152  → 0.75
//   w > 1366          → 1.0
// Without this, JS-computed pixel widths (sidebar, panels, node previews)
// wouldn't track the rest of the (rem-based) UI on low-res screens.
export function lowResScale(): number {
    if (typeof window === 'undefined') return 1;
    const w = window.innerWidth;
    if (w <= 768) return 1;
    if (w <= 1152) return 0.75;
    if (w <= 1366) return 0.85;
    return 1;
}

// Shorthand for `base * lowResScale()`. Used by px-based dimensions that
// can't be expressed in rem (e.g. JS-set widths, decorative sizes that
// would look wrong as text-relative). Variadic form scales a tuple.
export function scaled(base: number): number {
    return base * lowResScale();
}

// Min / max sidebar width in REM so the bounds shrink automatically with the
// global font-size scaling on low-res. At default 16px font: 18rem = 288px
// floor, 44rem = 704px ceiling. At 13.6px (≤1366px): 245px / 598px.
const MIN_PANEL_WIDTH_REM = 18;
const MAX_PANEL_WIDTH_REM = 44;
function remToPixels(rem: number): number {
    if (typeof window === 'undefined') return rem * 16;
    const fs = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
    return rem * fs;
}

// Convert viewport width units to pixels
export function vwToPixels(vw: number): number {
    if (typeof window === 'undefined') {
        return 400; // Fallback for SSR
    }
    return (vw * window.innerWidth) / 100;
}

// Min / max bounds for the chat sidebar's width, used by both the default
// computation below and the resize-drag clamp in ResizablePanel so the
// user can't drag the panel narrower / wider than these.
export function getMinPanelWidth(): number {
    return remToPixels(MIN_PANEL_WIDTH_REM);
}
export function getMaxPanelWidth(): number {
    return remToPixels(MAX_PANEL_WIDTH_REM);
}

// Get the default panel width in pixels, scaled to match the low-res
// font-size tiers and clamped to the min/max bounds.
export function getDefaultPanelWidth(): number {
    if (typeof window === 'undefined') return 400;
    const raw = vwToPixels(DEFAULT_PANEL_WIDTH_VW) * lowResScale();
    return Math.min(getMaxPanelWidth(), Math.max(getMinPanelWidth(), raw));
}
