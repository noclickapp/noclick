// The laptop sidebar's width: dragged from its edge within a small range,
// remembered on this device, and read by everything laid out beside it (the
// page, the builder chat), and whether it is folded to the rail, remembered the
// same way. The app and the developer console share both. Reads no app state.
import { useSyncExternalStore } from 'react';
import { createPanelWidth } from '@/ui/panelWidth';

export const SIDEBAR_WIDTH = 260;
export const SIDEBAR_RAIL_WIDTH = 56;
export const SIDEBAR_MIN_WIDTH = 220;
export const SIDEBAR_MAX_WIDTH = 360;

export const sidebarPanel = createPanelWidth({ key: 'nc-sidebar-width', initial: SIDEBAR_WIDTH, min: SIDEBAR_MIN_WIDTH, max: SIDEBAR_MAX_WIDTH });

export const clampSidebarWidth = sidebarPanel.clamp;
export const setSidebarWidth = sidebarPanel.set;
export const setSidebarResizing = sidebarPanel.setResizing;
export const useSidebarWidth = sidebarPanel.useWidth;
export const useSidebarResizing = sidebarPanel.useResizing;

/** What the sidebar takes from the left edge: its width, or the rail when collapsed. */
export function sidebarWidthFor(collapsed: boolean, open: number = SIDEBAR_WIDTH): number {
    return collapsed ? SIDEBAR_RAIL_WIDTH : open;
}

const COLLAPSED_KEY = 'nc-sidebar-collapsed';

let collapsed = (() => {
    if (typeof window === 'undefined') return false;
    try {
        return window.localStorage.getItem(COLLAPSED_KEY) === '1';
    } catch {
        // Storage blocked (private window, embedded preview): open, as by default.
        return false;
    }
})();
const collapsedListeners = new Set<() => void>();
const subscribeCollapsed = (listener: () => void) => {
    collapsedListeners.add(listener);
    return () => {
        collapsedListeners.delete(listener);
    };
};

function setSidebarCollapsed(next: boolean): void {
    collapsed = next;
    try {
        window.localStorage.setItem(COLLAPSED_KEY, next ? '1' : '0');
    } catch {
        // Not remembered this time; the fold still applies.
    }
    collapsedListeners.forEach((listener) => listener());
}

/** Whether the laptop sidebar is folded to its rail; the server renders it open and the client catches up. */
export function useSidebarCollapsed(): [boolean, (collapsed: boolean) => void] {
    return [useSyncExternalStore(subscribeCollapsed, () => collapsed, () => false), setSidebarCollapsed];
}
