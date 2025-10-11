// UI Constants for the NoClick application
// Centralizes common UI values to ensure consistency across components

// Default panel width as a percentage of viewport width
export const DEFAULT_PANEL_WIDTH_VW = 30;

// Convert viewport width units to pixels
export function vwToPixels(vw: number): number {
    if (typeof window === 'undefined') {
        return 400; // Fallback for SSR
    }
    return (vw * window.innerWidth) / 100;
}

// Get the default panel width in pixels
export function getDefaultPanelWidth(): number {
    return vwToPixels(DEFAULT_PANEL_WIDTH_VW);
}
