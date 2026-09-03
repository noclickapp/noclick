/**
 * Centralized navigation utilities for the dashboard.
 * Uses custom events to communicate between components while maintaining
 * optimistic state updates and URL persistence.
 *
 * Pattern:
 * 1. Caller dispatches event with desired navigation state
 * 2. Dashboard receives event, updates local state immediately (optimistic)
 * 3. Dashboard updates URL in background (for persistence)
 * 4. Child components receive updated props and render immediately
 */

// ============================================================================
// Types
// ============================================================================

export type DashboardTab = 'vite' | 'databases' | 'flow' | 'debug' | 'analytics' | 'dashboard' | 'settings';
// Drill-down sections of the Dashboard tab (?focus=). Kept here, next to the tab
// vocabulary, so URL encoding and the tab component agree on the names.
export const DASHBOARD_FOCUS_IDS = ['attention', 'runs', 'agents', 'files', 'credentials', 'triggers', 'upcoming', 'credits', 'notifications'] as const;
export type DashboardFocus = (typeof DASHBOARD_FOCUS_IDS)[number];
// Single source of truth for valid settings sections — Dashboard's URL parser
// and Settings' useUrlSyncedTab both validate against this list, so a section
// added here is automatically routable everywhere (a section missing from a
// hand-copied list silently falls back to 'usage').
export const SETTINGS_SECTIONS = ['usage', 'credentials', 'organization', 'developer', 'skills', 'notifications', 'popups', 'oauth-apps'] as const;
export type SettingsSection = (typeof SETTINGS_SECTIONS)[number];
export type OrgSettingsTab = 'overview' | 'sso' | 'danger';

export interface TabSwitchEventDetail {
  tab: DashboardTab;
  section?: SettingsSection;
  orgTab?: OrgSettingsTab;
  /** Dashboard tab only: open this section full-screen. */
  focus?: DashboardFocus;
}

/** A command-palette browser action handled by WorkflowBrowser. */
export type BrowserAction = 'create' | 'new-folder' | 'trash';

/** What to do once we're on the flow tab. Set by navigateToWorkflow /
 * triggerBrowserAction right before switching to the flow tab, then consumed by
 * WorkflowBrowser — see consumePendingFlowIntent. */
export type FlowIntent =
  | { kind: 'open'; workflow: { id: string; name: string } }
  | { kind: 'action'; action: BrowserAction };

// ============================================================================
// Navigation Functions
// ============================================================================

/**
 * Navigate to a specific dashboard tab.
 * @param tab - The tab to navigate to
 */
export function navigateToTab(tab: DashboardTab): void {
  window.dispatchEvent(new CustomEvent<TabSwitchEventDetail>('noclick:switch-tab', {
    detail: { tab },
    bubbles: true,
  }));
}

/** Open the Dashboard tab, optionally straight into one section's drill-down. */
export function navigateToDashboard(focus?: DashboardFocus): void {
  window.dispatchEvent(new CustomEvent<TabSwitchEventDetail>('noclick:switch-tab', {
    detail: { tab: 'dashboard', focus },
    bubbles: true,
  }));
}

/** Open a workflow on the canvas with one node selected — the same two-step
 * hand-off the approval feed used: Dashboard switches tabs and queues the
 * selection, then a late `select-node` catches an already-mounted canvas. */
export function goToWorkflowNode(workflowId: string, nodeId: string): void {
  window.dispatchEvent(new CustomEvent('noclick:navigate-to-node', { detail: { workflowId, nodeId } }));
  setTimeout(() => {
    document.dispatchEvent(new CustomEvent('noclick:workflow:select-node', { detail: { workflowId, nodeId } }));
  }, 200);
}

/**
 * Navigate to settings with optional section and org tab.
 * @param options - Navigation options
 */
export function navigateToSettings(options: {
  section?: SettingsSection;
  orgTab?: OrgSettingsTab;
} = {}): void {
  window.dispatchEvent(new CustomEvent<TabSwitchEventDetail>('noclick:switch-tab', {
    detail: {
      tab: 'settings',
      section: options.section,
      orgTab: options.orgTab,
    },
    bubbles: true,
  }));
}

/**
 * Navigate to organization settings.
 * Shorthand for navigateToSettings({ section: 'organization' })
 */
export function navigateToOrgSettings(orgTab?: OrgSettingsTab): void {
  navigateToSettings({ section: 'organization', orgTab });
}

/**
 * Navigate to usage dashboard.
 * Shorthand for navigateToSettings({ section: 'usage' })
 */
export function navigateToUsage(): void {
  navigateToSettings({ section: 'usage' });
}

/**
 * Go to the workflow browser: reset it to its root (close any open workflow /
 * folder) and switch to the flow tab. Shared by the command palette's "Go to
 * workflows" command and the "G W" keyboard shortcut.
 */
export function goToWorkflows(): void {
  window.dispatchEvent(new CustomEvent('noclick:workflow-browser-reset'));
  navigateToTab('flow');
}

// Flow-intent latch: set by navigateToWorkflow / triggerBrowserAction right
// before switching to the flow tab, consumed by WorkflowBrowser either
// synchronously via the noclick:flow-intent event (browser already mounted on the
// flow tab) or on mount (cross-tab — the browser mounts fresh and the event has
// already fired with no listener). This makes a palette "open X" / "create" feel
// as fast as a card click instead of a navigate() → URL → useEffect round-trip.
let pendingFlowIntent: FlowIntent | null = null;

/** Read and clear the pending flow intent (the event listener and the mount
 * effect both call this; whichever runs first wins, the other sees null). */
export function consumePendingFlowIntent(): FlowIntent | null {
  const intent = pendingFlowIntent;
  pendingFlowIntent = null;
  return intent;
}

function dispatchFlowIntent(intent: FlowIntent): void {
  pendingFlowIntent = intent;
  window.dispatchEvent(
    new CustomEvent<FlowIntent>('noclick:flow-intent', { detail: intent })
  );
  navigateToTab('flow');
}

/** Open a workflow in the flow editor as fast as a card click, from any screen. */
export function navigateToWorkflow(workflow: { id: string; name: string }): void {
  dispatchFlowIntent({ kind: 'open', workflow });
}

/** Trigger a workflow-browser action (create blank workflow / open the
 * new-folder dialog) from any screen, synchronously. */
export function triggerBrowserAction(action: BrowserAction): void {
  dispatchFlowIntent({ kind: 'action', action });
}


// ============================================================================
// Event Listener Hook Helper
// ============================================================================

/**
 * Encode a dashboard tab into URL search params — the single source of truth for
 * the tab→param mapping, shared by the NavBar's handleTabChange and the
 * event-based createTabSwitchHandler. Only tabs Dashboard's url→tab effect can
 * decode are written; the vite/databases home is left implicit (param untouched)
 * so we never stamp a ?tab= that won't round-trip on reload.
 */
export function applyTabToSearchParams(params: URLSearchParams, tab: string): void {
  if (tab === 'flow') {
    params.set('tab', 'workflows');
  } else if (tab === 'debug') {
    params.set('tab', 'debug');
  } else if (tab === 'analytics') {
    params.set('tab', 'analytics');
  } else if (tab === 'dashboard') {
    params.set('tab', 'dashboard');
    // Leaving the flow editor for the dashboard — drop the open-workflow deep-link params.
    params.delete('workflow');
    params.delete('node');
    params.delete('field');
  } else if (tab === 'settings') {
    params.set('tab', 'settings');
  }
  // Settings-only params don't belong on any other tab.
  if (tab !== 'settings') {
    params.delete('section');
    params.delete('orgTab');
  }
  // The dashboard's drill-down param doesn't belong on any other tab.
  if (tab !== 'dashboard') {
    params.delete('focus');
  }
}

/**
 * Create a handler function for the noclick:switch-tab event.
 * Use this in Dashboard to handle navigation events consistently.
 *
 * @param callbacks - Callbacks for handling navigation
 * @returns Event handler function
 */
export function createTabSwitchHandler(callbacks: {
  setSelectedTab: (tab: string) => void;
  setSettingsSection: (section: SettingsSection) => void;
  setSearchParams: (updater: (prev: URLSearchParams) => URLSearchParams, options?: { replace?: boolean }) => void;
}): (e: Event) => void {
  const { setSelectedTab, setSettingsSection, setSearchParams } = callbacks;

  return (e: Event) => {
    const customEvent = e as CustomEvent<TabSwitchEventDetail>;
    if (!customEvent.detail?.tab) return;

    const { tab, section, orgTab, focus } = customEvent.detail;

    // Optimistic, SYNCHRONOUS state update — this is what makes event-based
    // navigation as fast as a direct NavBar click (the tab switches in the same
    // render, instead of waiting for a navigate() → URL → useEffect → setState
    // round-trip).
    setSelectedTab(tab);

    if (tab === 'settings') {
      setSettingsSection(section ?? 'usage');
    }

    // Keep the URL in sync (background, for reload/deep-link/back) using the same
    // encoder as the NavBar. Previously only settings updated the URL, which left
    // other event-based navigations with a stale URL.
    setSearchParams(prev => {
      const newParams = new URLSearchParams(prev);
      applyTabToSearchParams(newParams, tab);

      if (tab === 'dashboard') {
        if (focus) newParams.set('focus', focus);
        else newParams.delete('focus');
      }

      // The event path owns the settings section in the URL (there's no Settings
      // component round-trip to set it, unlike a NavBar click).
      if (tab === 'settings') {
        const resolvedSection = section ?? 'usage';
        newParams.set('section', resolvedSection);
        if (orgTab) {
          newParams.set('orgTab', orgTab);
        } else if (resolvedSection !== 'organization') {
          newParams.delete('orgTab');
        }
      }

      return newParams;
    }, { replace: true });
  };
}
