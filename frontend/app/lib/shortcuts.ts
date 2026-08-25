// Central registry for the leader keyboard shortcuts (Linear-style two-key
// sequences). "G <key>" goes somewhere, "N <key>" creates something, "O <key>"
// opens the command palette scoped to a category. Keeping the key map here means
// the leader handler (useLeaderShortcuts), the palette's per-command shortcut
// hints, and the searchable shortcuts panel all stay in sync from one source.
// Each entry carries the matching palette `commandId` so the palette can show the
// keycaps next to the command it triggers.
import {
    navigateToTab,
    navigateToSettings,
    goToWorkflows,
    triggerBrowserAction,
} from '~/lib/navigation';
import { openCreateCredential } from '~/components/shared/popups/CreateCredentialDialog';

export interface LeaderShortcut {
    /** The second key pressed after the leader. */
    key: string;
    label: string;
    /** Matching command palette Cmd.id, so the palette can show this shortcut. */
    commandId: string;
    run: () => void;
}

// "G <key>" — go to a destination.
export const GOTO_DESTINATIONS: LeaderShortcut[] = [
    { key: 'w', label: 'Workflows', commandId: 'nav:workflows', run: goToWorkflows },
    { key: 'a', label: 'Approvals', commandId: 'nav:feed', run: () => navigateToTab('feed') },
    { key: 't', label: 'Trash', commandId: 'nav:trash', run: () => triggerBrowserAction('trash') },
    { key: 'u', label: 'Usage', commandId: 'nav:settings:usage', run: () => navigateToSettings({ section: 'usage' }) },
    { key: 'c', label: 'Credentials', commandId: 'nav:settings:credentials', run: () => navigateToSettings({ section: 'credentials' }) },
    { key: 'o', label: 'Organization', commandId: 'nav:settings:organization', run: () => navigateToSettings({ section: 'organization' }) },
    { key: 's', label: 'Skills', commandId: 'nav:settings:skills', run: () => navigateToSettings({ section: 'skills' }) },
    { key: 'n', label: 'Notifications', commandId: 'nav:settings:notifications', run: () => navigateToSettings({ section: 'notifications' }) },
    { key: 'd', label: 'Developer', commandId: 'nav:settings:developer', run: () => navigateToSettings({ section: 'developer' }) },
];

// "N <key>" — create something new.
export const NEW_ACTIONS: LeaderShortcut[] = [
    { key: 'w', label: 'New workflow', commandId: 'action:new-workflow', run: () => triggerBrowserAction('create') },
    { key: 'f', label: 'New folder', commandId: 'action:new-folder', run: () => triggerBrowserAction('new-folder') },
    { key: 'c', label: 'New credential', commandId: 'action:new-credential', run: openCreateCredential },
];

// "H <key>" — help. "H H" opens the in-app feedback popover.
export const HELP_ACTIONS: LeaderShortcut[] = [
    { key: 'h', label: 'Send feedback', commandId: 'action:send-feedback', run: openFeedback },
];

/** Command-palette scope opened by the "O" leader — matches a palette Section. */
export type PaletteScope = 'Workflows' | 'Credentials';

export interface OpenScope extends LeaderShortcut {
    scope: PaletteScope;
}

// "O <key>" — open the palette pre-scoped to a category of objects. The label is
// the scoped placeholder ("Open workflow…") and also the palette command title.
export const OPEN_SCOPES: OpenScope[] = [
    { key: 'w', label: 'Open workflow…', commandId: 'open:workflows', scope: 'Workflows', run: () => openCommandPaletteScoped('Workflows') },
    { key: 'c', label: 'Open credential…', commandId: 'open:credentials', scope: 'Credentials', run: () => openCommandPaletteScoped('Credentials') },
];

export interface ShortcutHint {
    keys: string[];
    /** True for leader sequences (G then U); false/absent for simultaneous combos (⌘/). */
    sequence?: boolean;
}

// palette command id -> the shortcut hint shown on that row. Leader entries are
// derived from the registries; the rest are single-key / combo shortcuts handled
// elsewhere (Dashboard, the palette itself) but surfaced here so they're learnable.
export const COMMAND_SHORTCUT_KEYS: Record<string, ShortcutHint> = {
    ...Object.fromEntries(GOTO_DESTINATIONS.map((d) => [d.commandId, { keys: ['G', d.key.toUpperCase()], sequence: true }])),
    ...Object.fromEntries(NEW_ACTIONS.map((a) => [a.commandId, { keys: ['N', a.key.toUpperCase()], sequence: true }])),
    ...Object.fromEntries(OPEN_SCOPES.map((s) => [s.commandId, { keys: ['O', s.key.toUpperCase()], sequence: true }])),
    ...Object.fromEntries(HELP_ACTIONS.map((a) => [a.commandId, { keys: ['H', a.key.toUpperCase()], sequence: true }])),
    'account:toggle-chat': { keys: ['/'] },
    'account:shortcuts': { keys: ['mod', '/'] },
};

// When a workflow canvas is open, "N" adds a node rather than arming the
// new-X leader. FlowCanvas flips this while mounted; useLeaderShortcuts checks it.
let _addNodeShortcutActive = false;
export function setAddNodeShortcutActive(active: boolean): void {
    _addNodeShortcutActive = active;
}
export function isAddNodeShortcutActive(): boolean {
    return _addNodeShortcutActive;
}

export const OPEN_COMMAND_PALETTE_EVENT = 'noclick:open-command-palette';

export interface OpenCommandPaletteDetail {
    /** Omitted/undefined opens the full palette; set restricts it to one scope. */
    scope?: PaletteScope;
    /** Which page to land on — 'root' (default) or the keyboard-shortcuts list. */
    page?: 'root' | 'shortcuts';
}

/** Open the command palette, optionally pre-scoped to a category. */
export function openCommandPalette(scope?: PaletteScope): void {
    window.dispatchEvent(
        new CustomEvent<OpenCommandPaletteDetail>(OPEN_COMMAND_PALETTE_EVENT, {
            detail: { scope },
        })
    );
}

/** Open the command palette straight to the keyboard-shortcuts list. */
export function openKeyboardShortcuts(): void {
    window.dispatchEvent(
        new CustomEvent<OpenCommandPaletteDetail>(OPEN_COMMAND_PALETTE_EVENT, {
            detail: { page: 'shortcuts' },
        })
    );
}

/** Open the command palette pre-scoped to a category (consumed by CommandPalette). */
export function openCommandPaletteScoped(scope: PaletteScope): void {
    openCommandPalette(scope);
}

export const OPEN_FEEDBACK_EVENT = 'noclick:open-feedback';

/** Open the in-app feedback popover (the navbar FeedbackButton listens for this). */
export function openFeedback(): void {
    window.dispatchEvent(new Event(OPEN_FEEDBACK_EVENT));
}
