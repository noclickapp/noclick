// The laptop sidebar's width: dragged from its edge within a small range,
// remembered on this device, and read by everything laid out beside it (the
// page, the builder chat). The app and the developer console share it, and
// whether it is folded to the rail.
import { useCachedValtioState } from '~/hooks/useCachedValtioState';
import { createPanelWidth } from './panelWidth';

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

/** Whether the laptop sidebar is folded to its rail, remembered on this device. */
export function useSidebarCollapsed(): [boolean, (collapsed: boolean) => void] {
    return useCachedValtioState<boolean>('dashboard', 'sidebarCollapsed', false, true);
}

/** What the sidebar takes from the left edge: its width, or the rail when collapsed. */
export function sidebarWidthFor(collapsed: boolean, open: number = SIDEBAR_WIDTH): number {
    return collapsed ? SIDEBAR_RAIL_WIDTH : open;
}
