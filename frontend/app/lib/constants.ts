// UI Constants for the NoClick application
// Centralizes common UI values to ensure consistency across components

// Default panel width as a percentage of viewport width
export const DEFAULT_PANEL_WIDTH_VW = 30;

// Min / max sidebar width in rem, so the bounds follow the browser's font size:
// 18rem = 288px floor, 44rem = 704px ceiling at the default 16px.
const MIN_PANEL_WIDTH_REM = 18;
const MAX_PANEL_WIDTH_REM = 44;
// Read once: reading it on every call forced a style recalculation mid-render
// (ResizablePanel's width bounds read it on each render).
let rootFontSize: number | null = null;

function remToPixels(rem: number): number {
    if (typeof window === 'undefined') return rem * 16;
    rootFontSize ??= parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
    return rem * rootFontSize;
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

// Get the default panel width in pixels, clamped to the min/max bounds.
export function getDefaultPanelWidth(): number {
    if (typeof window === 'undefined') return 400;
    const raw = vwToPixels(DEFAULT_PANEL_WIDTH_VW);
    return Math.min(getMaxPanelWidth(), Math.max(getMinPanelWidth(), raw));
}
