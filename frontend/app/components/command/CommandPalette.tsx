// Global command palette, mounted once in the dashboard so it opens on ⌘K / Ctrl+K (and the sidebar's search) from
// every screen. It goes anywhere: every page and the places inside them (destinations.ts), the places a deployment
// registers (sources.ts), and the person's own things: automations and their folders, connected accounts, and the
// resources and channels their pages have already read. It also creates, opens one category ("O W"), and holds the
// account's commands. A row is found by its name, the other words people use for it and where it lives
// (`scoreNamed`); what someone runs often floats up, and the latest are offered before anything is typed. Nothing is
// read per keystroke: workflows and accounts are refreshed once each time it opens.

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import {
    Search,
    Plus,
    Folder,
    FolderPlus,
    KeyRound,
    Globe,
    MessageCircle,
    MessageSquarePlus,
    Keyboard,
    LogOut,
    Phone,
    Sun,
    Moon,
    Monitor,
    Workflow as WorkflowIcon,
    CornerDownLeft,
    ChevronLeft,
    ArrowRight,
} from 'lucide-react';
import { cn } from '~/lib/utils';
import { isTextEntryTarget } from '~/lib/keyboard';
import { isLocalEdition } from '~/lib/edition';
import { useAnalytics } from '~/lib/analytics';
import { EVENTS } from '~/lib/analytics-events';
import {
    GOTO_DESTINATIONS,
    NEW_ACTIONS,
    OPEN_SCOPES,
    COMMAND_SHORTCUT_KEYS,
    OPEN_COMMAND_PALETTE_EVENT,
    openFeedback,
    type OpenCommandPaletteDetail,
    type PaletteScope,
} from '~/lib/shortcuts';
import {
    navigateToAccount,
    navigateToFolder,
    navigateToTab,
    navigateToWorkflow,
    triggerBrowserAction,
    type SettingsSection,
} from '~/lib/navigation';
import { MENU_SURFACE } from '~/components/shell/menus';
import { useConnectedAccounts } from '~/components/shell/connections/accounts';
import { resourceAddress, visibleKinds } from '~/components/shell/resources/kinds';
import { hasPlatformResources } from '~/components/shell/resources/platform';
import { useSettingsSections } from '~/components/settings/sections';
import { NoClickMCPSetupModal } from '~/components/workflow/MCPConnectModal';
import { getCredentialIcon } from '~/utils/credentialIcons';
import { fuzzyFilter } from '~/utils/fuzzySearch';
import { BrandIcon } from '~/components/shared/BrandIcon';
import { openCreateCredential } from '~/components/shared/popups/CreateCredentialDialog';
import { relativeShort } from '~/components/workflow/WorkflowBrowserCards';
import { useCachedValtioState } from '~/hooks/useCachedValtioState';
import { useCredentialList } from '~/hooks/useCachedCredentialList';
import { useInstanceCapabilities } from '~/hooks/useInstanceCapabilities';
import { useOrgContext } from '~/hooks/useOrgContext';
import { useWorkflowBrowserDataContext } from '~/hooks/WorkflowBrowserDataProvider';
import { useListKeyboardNav } from '~/hooks/useListKeyboardNav';
import { useTheme } from '~/hooks/useTheme';
import type { Theme } from '~/lib/theme';
import { KeyHint, SequenceKeyHint } from '~/components/shared/KeyHint';
import { NodeIconStack } from '~/components/shared/NodeIconStack';
import { workflowIconTypes } from '~/lib/workflowBrowserStore';
import { appDestinations } from './destinations';
import { readUses, recordUse, type Use } from './history';
import { layoutCommands, PLACES, type Cmd, type Section } from './layout';
import {
    forgetPaletteEntries,
    paletteSources,
    useRememberedPaletteEntries,
    type HoldingPage,
    type PaletteEntry,
    type PaletteIcon,
} from './sources';

// The shell's menu language (the composer's "+", Connect): its surface, a roomy search, sentence-case sections.
const SEARCH_ROW = 'flex h-14 items-center gap-3 border-b border-border px-5 dark:border-foreground/[0.07]';
const SEARCH_ICON = 'h-[18px] w-[18px] shrink-0 text-muted-foreground';
const SEARCH_INPUT = 'h-full w-full bg-transparent text-[15px] text-foreground placeholder:text-[hsl(var(--placeholder))] focus:outline-none';
const LIST = 'max-h-[min(52vh,460px)] overflow-y-auto scrollbar-subtle p-2';
const SECTION = 'px-3 pb-1.5 pt-3 text-[12.5px] font-medium text-muted-foreground first:pt-1.5';
const EMPTY = 'px-3 py-10 text-center text-[14px] text-muted-foreground';
const FOOTER = 'flex items-center gap-4 border-t border-border px-5 py-3 text-[12px] text-muted-foreground dark:border-foreground/[0.07]';

// The app shell's pages and words; the open edition runs the tabbed layout, where automations are workflows.
const SHELL = !isLocalEdition();

const SECTION_TITLES: Partial<Record<Section | 'Recent', string>> = {
    Workflows: SHELL ? 'Automations' : 'Workflows',
    Credentials: SHELL ? 'Accounts' : 'Credentials',
};

// Appearance options surfaced as Account commands (mirrors the account menu's picker). The active one is marked.
const THEME_OPTIONS: { value: Theme; label: string; icon: PaletteIcon; keywords: string }[] = [
    { value: 'light', label: 'light', icon: Sun, keywords: 'bright day white appearance mode' },
    { value: 'dark', label: 'dark', icon: Moon, keywords: 'night black appearance mode' },
    { value: 'system', label: 'system', icon: Monitor, keywords: 'auto os default appearance mode' },
];

const asCmd = (section: Section) => (entry: PaletteEntry): Cmd => ({ ...entry, section });

// Reference shown in the searchable "Keyboard shortcuts" sub-page. The Go to / Open
// groups are derived from the shortcut registry so they can't drift from what the
// leader-key handler actually does. `sequence` keys are pressed one after another
// (G then W), not together.
interface ShortcutItem {
    keys: string[];
    sequence?: boolean;
    label: string;
}
const SHORTCUT_GROUPS: { title: string; items: ShortcutItem[] }[] = [
    {
        title: 'General',
        items: [
            { keys: ['mod', 'K'], label: 'Open command palette' },
            { keys: ['mod', '/'], label: 'Open keyboard shortcuts' },
            { keys: ['/'], label: 'Open chat sidebar' },
            { keys: ['['], label: 'Toggle workspace sidebar' },
            { keys: ['C'], label: 'Card view (browser)' },
            { keys: ['L'], label: 'List view (browser)' },
            { keys: ['esc'], label: 'Close command palette' },
        ],
    },
    {
        // Single-key shortcuts active on the workflow editor; ignored while
        // typing in a field. Keep in sync with useWorkflowKeyboardShortcuts and
        // FlowCanvas's canvas key handlers.
        title: 'Workflow editor',
        items: [
            { keys: ['F'], label: 'Toggle flow helper' },
            { keys: ['C'], label: 'Open config tab' },
            { keys: ['K'], label: 'Open credentials tab' },
            { keys: ['U'], label: 'Open UX tab' },
            { keys: ['W'], label: 'Flow view' },
            { keys: ['I'], label: 'Interface view' },
            { keys: ['L'], label: 'Logs view' },
            { keys: ['S'], label: 'Setup view' },
            { keys: ['V'], label: 'Version history' },
            { keys: ['N'], label: 'Add a node' },
            { keys: ['up', 'down', 'left', 'right'], label: 'Move between nodes' },
            { keys: ['enter'], label: 'Open selected node' },
            { keys: ['esc'], label: 'Defocus field / collapse flow helper' },
            { keys: ['D'], label: 'Toggle node disabled' },
            { keys: ['M'], label: 'Toggle mock output' },
            { keys: ['mod', 'Z'], label: 'Undo' },
            { keys: ['mod', 'shift', 'Z'], label: 'Redo' },
        ],
    },
    {
        title: 'Go to',
        items: GOTO_DESTINATIONS.map((d) => ({
            keys: ['G', d.key.toUpperCase()],
            sequence: true,
            label: d.label,
        })),
    },
    {
        title: 'New',
        items: NEW_ACTIONS.map((a) => ({
            keys: ['N', a.key.toUpperCase()],
            sequence: true,
            label: a.label,
        })),
    },
    {
        title: 'Open',
        items: OPEN_SCOPES.map((s) => ({
            keys: ['O', s.key.toUpperCase()],
            sequence: true,
            label: s.label,
        })),
    },
];

type Row = { type: 'header'; title: string } | { type: 'item'; cmd: Cmd; index: number };

/** `hiddenSettings`: the Settings sections the host shows as pages of their own, as it tells Settings. */
export function CommandPalette({ hiddenSettings }: { hiddenSettings?: readonly SettingsSection[] }) {
    const [open, setOpen] = useState(false);
    const [query, setQuery] = useState('');
    const { logActivity } = useAnalytics();
    const [page, setPage] = useState<'root' | 'shortcuts'>('root');
    // Snapshot the page the palette opened to, so the open-analytics effect can tag
    // the event without re-firing when the page changes while already open.
    const openedToRef = useRef(page);
    openedToRef.current = page;
    // Power-user signal: fire once each time the palette opens (any entry path).
    // `opened_to` distinguishes opening the keyboard-shortcuts reference (⌘/ or "?",
    // the navbar item) from opening the palette to navigate/run commands ('root'),
    // so we can measure whether viewing shortcuts converts to real palette usage.
    useEffect(() => {
        if (open) logActivity(EVENTS.COMMAND_PALETTE_OPENED, { opened_to: openedToRef.current });
    }, [open, logActivity]);
    // Non-null when opened via an "O <key>" shortcut — restricts results to one
    // section (e.g. Workflows) and swaps the placeholder ("Open workflow…").
    const [scope, setScope] = useState<PaletteScope | null>(null);
    // Platform MCP setup guides — opened by the "Set up NoClick MCP" action.
    const [mcpSetupOpen, setMcpSetupOpen] = useState(false);
    const inputRef = useRef<HTMLInputElement>(null);
    const listRef = useRef<HTMLDivElement>(null);
    const store = useWorkflowBrowserDataContext();
    const { loadAllWorkflows, getAllWorkflows, getAllFolders } = store;
    const [theme, setTheme] = useTheme();
    const { billing } = useInstanceCapabilities();
    const settingsSections = useSettingsSections(hiddenSettings);
    // Accounts are read again each time the palette opens, never on a closed one.
    const { credentials } = useCredentialList(open);
    const accounts = useConnectedAccounts(credentials);
    const remembered = useRememberedPaletteEntries();
    const [uses, setUses] = useState<Record<string, Use>>({});

    // What registered sources add, by source.
    const [added, setAdded] = useState<Record<number, readonly PaletteEntry[]>>({});
    const reporters = useMemo(
        () => paletteSources().map((_, i) => (entries: readonly PaletteEntry[]) => setAdded((prev) => ({ ...prev, [i]: entries }))),
        []
    );

    // What pages handed over belongs to the workspace they read it in.
    const [orgContext] = useOrgContext();
    const workspaceRef = useRef(orgContext.id);
    useEffect(() => {
        if (workspaceRef.current === orgContext.id) return;
        workspaceRef.current = orgContext.id;
        forgetPaletteEntries();
    }, [orgContext.id]);

    // Shared with Dashboard — toggling this opens/closes the chat sidebar.
    const [, setChatExpanded] = useCachedValtioState<boolean>(
        'dashboard',
        'isChatExpanded',
        false,
        true
    );

    // ── Global shortcuts: ⌘K toggles the palette; ⌘/ (or a bare "?") opens it
    // straight to the keyboard-shortcuts panel. ───────────────────────────────
    useEffect(() => {
        const onKey = (e: KeyboardEvent) => {
            const mod = e.metaKey || e.ctrlKey;
            if (mod && e.key.toLowerCase() === 'k') {
                e.preventDefault();
                setOpen((o) => !o);
                return;
            }
            // ⌘/ or Ctrl+/ anywhere, or "?" when not typing in a field.
            const slashCombo = mod && e.key === '/';
            const questionKey =
                e.key === '?' &&
                !mod &&
                !e.altKey &&
                !isTextEntryTarget(e.target);
            if (slashCombo || questionKey) {
                e.preventDefault();
                setPage('shortcuts');
                setOpen(true);
                return;
            }
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, []);

    // Open pre-scoped to a category via an "O <key>" shortcut (see shortcuts.ts).
    useEffect(() => {
        const onScopedOpen = (e: Event) => {
            const detail = (e as CustomEvent<OpenCommandPaletteDetail>).detail;
            setScope(detail?.scope ?? null);
            setPage(detail?.page ?? 'root');
            setQuery('');
            setOpen(true);
        };
        window.addEventListener(OPEN_COMMAND_PALETTE_EVENT, onScopedOpen);
        return () =>
            window.removeEventListener(OPEN_COMMAND_PALETTE_EVENT, onScopedOpen);
    }, []);

    // Reset transient state when closed; on open, read what was run here before and
    // force-refresh the full workflow set once so jump-to-workflow shows current node
    // counts / types (cached entries can be stale). The ref guards against the effect
    // re-firing when loadAllWorkflows' identity changes (folderTree updates) mid-open.
    const refreshedThisOpenRef = useRef(false);
    useEffect(() => {
        if (!open) {
            setQuery('');
            setPage('root');
            setScope(null);
            refreshedThisOpenRef.current = false;
        } else if (!refreshedThisOpenRef.current) {
            refreshedThisOpenRef.current = true;
            setUses(readUses());
            loadAllWorkflows(true);
        }
    }, [open, loadAllWorkflows]);

    // Escape closes ONLY the palette. A capture-phase document listener (active
    // while open) intercepts Escape before any bubble-phase handler — notably the
    // dashboard's global Escape handler that closes the NoClick chat sidebar, and
    // Radix's own dismiss. We then close the palette ourselves. Capture + a
    // document-level listener is robust regardless of where focus sits (the React
    // onKeyDown on the portaled content is not), which is why the in-component
    // handler alone wasn't enough.
    useEffect(() => {
        if (!open) return;
        const onEscapeCapture = (e: KeyboardEvent) => {
            if (e.key !== 'Escape') return;
            e.preventDefault();
            e.stopImmediatePropagation();
            setOpen(false);
        };
        document.addEventListener('keydown', onEscapeCapture, true);
        return () =>
            document.removeEventListener('keydown', onEscapeCapture, true);
    }, [open]);

    const close = useCallback(() => setOpen(false), []);
    const run = useCallback(
        (cmd: Cmd) => {
            if (!cmd.keepOpen) {
                close();
                recordUse(cmd.id);
            }
            cmd.run();
        },
        [close]
    );

    // ── All workflows, deduped + most-recent first ─────────────────────────
    // Dedup is structural (getAllWorkflows dedups by id, own wins ties); we only
    // project + sort by recency here.
    const allWorkflows = useMemo(
        () =>
            getAllWorkflows()
                .map((wf) => ({
                    id: wf.id,
                    name: wf.name,
                    updated_at: wf.updated_at,
                    node_count: wf.node_count,
                    // Harness-expanded (`agent:<kind>`) so agent rows show the
                    // actual harness mark, same as the browser card/list.
                    node_types: workflowIconTypes(wf),
                }))
                .sort((a, b) => (b.updated_at ?? '').localeCompare(a.updated_at ?? '')),
        [getAllWorkflows],
    );
    const allFolders = useMemo(() => getAllFolders(), [getAllFolders]);

    // ── Command catalogue ──────────────────────────────────────────────────
    const allCommands = useMemo<Cmd[]>(() => {
        const signOut = async () => {
            await fetch('/dashboard', { method: 'POST', body: new FormData() });
            window.location.href = '/auth/login';
        };
        const registered = Object.values(added).flat();

        const workflowCmds: Cmd[] = allWorkflows.map((wf) => {
            const n = wf.node_count ?? 0;
            const rel = relativeShort(wf.updated_at);
            const meta = [`${n} ${n === 1 ? 'node' : 'nodes'}`, rel]
                .filter(Boolean)
                .join(' · ');
            return {
                id: `wf:${wf.id}`,
                label: wf.name || 'Untitled',
                section: 'Workflows',
                icon: WorkflowIcon,
                nodeTypes: wf.node_types,
                meta,
                // Opens the flow synchronously (setSelectedWorkflow → FlowCanvas
                // mounts from cache) whether the browser is already mounted
                // (flow tab) or we're switching from another screen — no
                // navigate() → URL → useEffect round-trip. See navigateToWorkflow.
                run: () =>
                    navigateToWorkflow({
                        id: wf.id,
                        name: wf.name || 'Untitled',
                    }),
            };
        });
        const folderCmds: Cmd[] = allFolders.map((f) => ({
            id: `folder:${f.id}`,
            label: f.name,
            section: 'Workflows',
            icon: Folder,
            keywords: 'folder',
            run: () => navigateToFolder(f.id),
        }));

        // An account opens its page under Connections; the open edition keeps accounts in Settings, so there it opens
        // the account in the credential dialog. A phone number is a resource, with its own page.
        const accountCmds: Cmd[] = accounts.map(({ credential, app, line, problem }) => {
            if (SHELL && credential.credential_type === 'phone_number') {
                return {
                    id: `resource:numbers:${credential.id}`,
                    label: credential.name,
                    context: 'Numbers',
                    section: 'Resources',
                    icon: Phone,
                    run: () => navigateToTab('resources', resourceAddress('numbers', { resource: credential.id })),
                };
            }
            const { Icon, iconColor, hasServiceIcon } = getCredentialIcon(credential.credential_type, credential.metadata);
            return {
                id: `cred:${credential.id}`,
                label: app,
                context: line,
                section: 'Credentials',
                icon: Icon,
                iconColor: iconColor || (hasServiceIcon ? 'text-foreground' : 'text-muted-foreground'),
                keywords: `${line} ${credential.name}`,
                meta: problem,
                run: SHELL
                    ? () => navigateToAccount(credential.id)
                    : () => openCreateCredential({ credentialType: credential.credential_type, credentialId: credential.id }),
            };
        });

        const heldCmds: Cmd[] = (Object.entries(remembered) as [HoldingPage, readonly PaletteEntry[]][]).flatMap(([page, entries]) =>
            entries.map(asCmd(page))
        );

        const navCmds: Cmd[] = [
            ...appDestinations({
                shell: SHELL,
                kinds: visibleKinds({ platform: hasPlatformResources() }),
                billing,
                inOrganization: !!orgContext.id,
                settings: settingsSections,
            }),
            ...registered.filter((e) => !e.action),
        ].map(asCmd('Go to'));

        const setupCmds: Cmd[] = [
            {
                id: 'setup:noclick-mcp',
                label: 'Set up MCP…',
                section: 'Setup',
                icon: Globe,
                keywords: 'noclick mcp server connect claude cursor codex chatgpt windsurf zed model context protocol api setup install',
                // Per-client setup guides for the platform MCP server —
                // build/run workflows from any MCP client.
                run: () => setMcpSetupOpen(true),
            },
        ];

        const actionCmds: Cmd[] = [
            {
                id: 'action:new-workflow',
                label: SHELL ? 'Create new automation…' : 'Create new workflow…',
                section: 'Actions',
                icon: Plus,
                keywords: 'new add blank workflow automation',
                // Fires synchronously (creates + shows the spinner / opens the
                // dialog) from any screen — see triggerBrowserAction.
                run: () => triggerBrowserAction('create'),
            },
            {
                id: 'action:new-folder',
                label: 'Create new folder…',
                section: 'Actions',
                icon: FolderPlus,
                keywords: 'new add directory',
                run: () => triggerBrowserAction('new-folder'),
            },
            {
                id: 'action:new-credential',
                label: 'Create new credential…',
                section: 'Actions',
                icon: KeyRound,
                keywords: 'new add connect service oauth api key token integration account login',
                // Opens the global create-credential dialog over the current
                // screen (no forced navigation) — see GlobalCreateCredentialDialog.
                run: () => openCreateCredential(),
            },
        ];

        // "Open X…" commands (one per O-shortcut). Selecting one switches the
        // palette into that scope (keepOpen) — the same mode "O <key>" opens.
        const openCmds: Cmd[] = OPEN_SCOPES.map((s): Cmd => ({
            id: s.commandId,
            label: s.label,
            section: 'Open',
            icon: s.scope === 'Credentials' ? KeyRound : WorkflowIcon,
            keywords: 'open jump search',
            keepOpen: true,
            run: () => {
                setQuery('');
                setScope(s.scope);
            },
        }));

        const accountCmdsList: Cmd[] = [
            ...registered.filter((e) => e.action).map(asCmd('Account')),
            {
                id: 'account:toggle-chat',
                label: 'Toggle chat sidebar',
                section: 'Account',
                icon: MessageCircle,
                keywords: 'ai assistant agent copilot collapse expand panel',
                run: () => setChatExpanded((p) => !p),
            },
            ...THEME_OPTIONS.map(
                (opt): Cmd => ({
                    id: `account:theme:${opt.value}`,
                    label: `Switch to ${opt.label} theme`,
                    section: 'Account',
                    icon: opt.icon,
                    keywords: `theme appearance color scheme ${opt.keywords}`,
                    // Mark the active choice; closes on select like every other command.
                    meta: theme === opt.value ? 'Active' : undefined,
                    run: () => setTheme(opt.value),
                })
            ),
            {
                id: 'account:shortcuts',
                label: 'Open keyboard shortcuts',
                section: 'Account',
                icon: Keyboard,
                keywords: 'keys help hotkeys',
                keepOpen: true,
                run: () => setPage('shortcuts'),
            },
            {
                id: 'action:send-feedback',
                label: 'Send feedback',
                section: 'Account',
                icon: MessageSquarePlus,
                keywords: 'bug report idea help support contact',
                run: openFeedback,
            },
            {
                id: 'account:sign-out',
                label: 'Sign out',
                section: 'Account',
                icon: LogOut,
                keywords: 'log out logout exit',
                run: signOut,
            },
        ];

        // A page may hand over something an account row already holds (a number): the first one stays.
        const seen = new Set<string>();
        return [
            ...workflowCmds,
            ...folderCmds,
            ...accountCmds,
            ...heldCmds,
            ...navCmds,
            ...actionCmds,
            ...openCmds,
            ...setupCmds,
            ...accountCmdsList,
        ].filter((c) => {
            if (seen.has(c.id)) return false;
            seen.add(c.id);
            return true;
        });
    }, [allWorkflows, allFolders, accounts, remembered, added, billing, orgContext.id, settingsSections, setChatExpanded, theme, setTheme]);

    // ── Filter + group ─────────────────────────────────────────────────────
    const { rows, flat } = useMemo(() => {
        const builtRows: Row[] = [];
        const flatList: Cmd[] = [];
        for (const section of layoutCommands(allCommands, query, scope, uses)) {
            // A scope ("O W") is one section, so its header would only repeat the placeholder.
            if (!scope) builtRows.push({ type: 'header', title: SECTION_TITLES[section.title] ?? section.title });
            for (const cmd of section.items) {
                builtRows.push({ type: 'item', cmd, index: flatList.length });
                flatList.push(cmd);
            }
        }
        return { rows: builtRows, flat: flatList };
    }, [allCommands, query, scope, uses]);

    const {
        index: highlighted,
        setIndex: setHighlighted,
        handleKeyDown,
    } = useListKeyboardNav({
        count: page === 'root' ? flat.length : 0,
        active: open && page === 'root',
        wrap: true,
        onSelect: (i) => {
            const cmd = flat[i];
            if (cmd) run(cmd);
        },
        // Escape is owned by the capture-phase document listener above, so the
        // list-nav hook doesn't handle it here.
    });

    // Delegate the navigation keys (↑/↓/↵) to the list-nav handler. Escape is
    // intercepted by the capture listener above (it never reaches here), so we
    // skip it defensively.
    const onContentKeyDown = useCallback(
        (e: React.KeyboardEvent) => {
            if (e.key === 'Escape') return;
            // Backspace on an empty query in a scoped ("O W") palette steps back
            // out to the full command palette instead of doing nothing.
            if (e.key === 'Backspace' && scope && query === '') {
                e.preventDefault();
                setScope(null);
                return;
            }
            handleKeyDown(e);
        },
        [handleKeyDown, scope, query]
    );

    // Reset highlight whenever the result set / page changes.
    useEffect(() => {
        setHighlighted(0);
    }, [query, page, open, setHighlighted]);

    // Keep the highlighted row in view as you arrow through.
    useEffect(() => {
        if (!open) return;
        const el = listRef.current?.querySelector<HTMLElement>(
            `[data-cmd-index="${highlighted}"]`
        );
        el?.scrollIntoView({ block: 'nearest' });
    }, [highlighted, open]);

    return (
        <>
            {paletteSources().map((Source, i) => (
                <Suspense key={i} fallback={null}>
                    <Source onEntries={reporters[i]} />
                </Suspense>
            ))}
            <Dialog.Root open={open} onOpenChange={setOpen}>
                <Dialog.Portal>
                    <Dialog.Overlay className="fixed inset-0 z-[100] bg-foreground/[0.08] dark:bg-background/60" />
                    <Dialog.Content
                        data-testid="command-palette"
                        aria-describedby={undefined}
                        onOpenAutoFocus={(e) => {
                            e.preventDefault();
                            inputRef.current?.focus();
                        }}
                        onKeyDown={onContentKeyDown}
                        // No enter/exit animation — it pops in (and out) instantly.
                        // Without any CSS animation, Radix also unmounts immediately on
                        // close instead of waiting for animationend. Centered with
                        // -translate-x-1/2 (a static transform, not animated). In the shell's menu surface.
                        className={cn('fixed left-1/2 top-[14vh] z-[101] w-[calc(100vw-32px)] max-w-[640px] -translate-x-1/2 overflow-hidden rounded-[26px] focus:outline-none', MENU_SURFACE)}
                    >
                        <Dialog.Title className="sr-only">
                            Command palette
                        </Dialog.Title>

                        {page === 'root' ? (
                            <>
                                {/* Search — in a scope ("O W") the leading glyph becomes
                                    the scope's icon (workflow) instead of the magnifier. */}
                                <div className={SEARCH_ROW}>
                                    {scope === 'Workflows' ? (
                                        <WorkflowIcon className={SEARCH_ICON} />
                                    ) : scope === 'Credentials' ? (
                                        <KeyRound className={SEARCH_ICON} />
                                    ) : (
                                        <Search className={SEARCH_ICON} />
                                    )}
                                    <input
                                        ref={inputRef}
                                        value={query}
                                        onChange={(e) => setQuery(e.target.value)}
                                        placeholder={
                                            scope
                                                ? OPEN_SCOPES.find(
                                                      (s) => s.scope === scope
                                                  )?.label ?? 'Search…'
                                                : 'Search or go anywhere…'
                                        }
                                        className={SEARCH_INPUT}
                                    />
                                    <KeyHint keys={['esc']} />
                                </div>

                                {/* Results */}
                                <div
                                    ref={listRef}
                                    className={LIST}
                                >
                                    {rows.length === 0 ? (
                                        <div className={EMPTY}>
                                            {query
                                                ? `No results for “${query}”`
                                                : scope === 'Credentials'
                                                  ? `No ${(SECTION_TITLES.Credentials ?? 'credentials').toLowerCase()} yet`
                                                  : scope === 'Workflows'
                                                    ? `No ${(SECTION_TITLES.Workflows ?? 'workflows').toLowerCase()} yet`
                                                    : 'No results'}
                                        </div>
                                    ) : (
                                        rows.map((row, i) =>
                                            row.type === 'header' ? (
                                                <div
                                                    key={`h:${row.title}:${i}`}
                                                    data-cmd-section
                                                    className={SECTION}
                                                >
                                                    {row.title}
                                                </div>
                                            ) : (
                                                <CommandRow
                                                    key={row.cmd.id}
                                                    cmd={row.cmd}
                                                    active={
                                                        row.index === highlighted
                                                    }
                                                    index={row.index}
                                                    onHover={() =>
                                                        setHighlighted(row.index)
                                                    }
                                                    onSelect={() => run(row.cmd)}
                                                />
                                            )
                                        )
                                    )}
                                </div>

                                {/* Footer */}
                                <div className={FOOTER}>
                                    <span className="flex items-center gap-1.5">
                                        <KeyHint keys={['up', 'down']} /> Navigate
                                    </span>
                                    <span className="flex items-center gap-1.5">
                                        <KeyHint keys={['enter']} /> Open
                                    </span>
                                    <span className="flex items-center gap-1.5">
                                        <KeyHint keys={['esc']} /> Close
                                    </span>
                                </div>
                            </>
                        ) : (
                            <ShortcutsPage onBack={() => setPage('root')} />
                        )}
                    </Dialog.Content>
                </Dialog.Portal>
                <NoClickMCPSetupModal open={mcpSetupOpen} onClose={() => setMcpSetupOpen(false)} />
            </Dialog.Root>
        </>
    );
}

function CommandRow({
    cmd,
    active,
    index,
    onHover,
    onSelect,
}: {
    cmd: Cmd;
    active: boolean;
    index: number;
    onHover: () => void;
    onSelect: () => void;
}) {
    const Icon = cmd.icon;
    const shortcut = COMMAND_SHORTCUT_KEYS[cmd.id];
    return (
        <button
            type="button"
            data-cmd-index={index}
            data-active={active || undefined}
            onMouseMove={onHover}
            onClick={onSelect}
            className={cn(
                'group flex h-11 w-full items-center gap-3.5 rounded-[16px] px-3 text-left outline-none transition-colors',
                active && 'bg-foreground/[0.07]'
            )}
        >
            {cmd.iconColor !== undefined ? (
                // Brand/service rows keep their brand color via BrandIcon.
                <BrandIcon
                    Icon={Icon}
                    iconColor={cmd.iconColor}
                    className="h-[18px] w-[18px] shrink-0"
                />
            ) : (
                <Icon className="h-[18px] w-[18px] shrink-0 text-foreground/85 [stroke-width:1.75]" />
            )}
            {/* Its name, then where it lives; the place gives way first on a narrow screen. */}
            <span className="flex min-w-0 flex-1 items-baseline gap-2">
                <span className="truncate text-[14.5px] text-foreground">{cmd.label}</span>
                {cmd.context && (
                    <span data-cmd-context className="shrink-[3] truncate text-[13px] text-muted-foreground">
                        {cmd.context}
                    </span>
                )}
            </span>
            {cmd.nodeTypes && cmd.nodeTypes.length > 0 && (
                <NodeIconStack
                    nodeTypes={cmd.nodeTypes}
                    size="md"
                    maxShown={5}
                    // No dash-filter here: control-flow nodes (delay, filter,
                    // merge, …) have single-word types and would otherwise be
                    // dropped, leaving simple workflows with no icons. Show an
                    // icon for any node type the registry resolves. Sticky notes
                    // are the only non-functional type excluded.
                    filter={(t) => t !== 'sticky-note'}
                    bare
                    className="shrink-0 max-sm:hidden"
                />
            )}
            {cmd.meta && (
                <span className="shrink-0 whitespace-nowrap text-[12.5px] text-muted-foreground max-sm:hidden">
                    {cmd.meta}
                </span>
            )}
            {/* Shortcut hint so people learn it in place: sequences as "G then U",
                combos (⌘/) as adjacent keycaps. */}
            {shortcut &&
                (shortcut.sequence ? (
                    <SequenceKeyHint keys={shortcut.keys} className="shrink-0 max-sm:hidden" />
                ) : (
                    <KeyHint keys={shortcut.keys} className="shrink-0 max-sm:hidden" />
                ))}
            {PLACES.has(cmd.section) ? (
                <ArrowRight
                    className={cn(
                        'h-4 w-4 shrink-0',
                        active ? 'text-muted-foreground' : 'text-muted-foreground/60'
                    )}
                />
            ) : (
                active && (
                    <CornerDownLeft className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                )
            )}
        </button>
    );
}

// Sequence shortcuts render with "then"; simultaneous combos (⌘K) render as
// adjacent keycaps.
function ShortcutKeys({ item }: { item: ShortcutItem }) {
    return item.sequence ? (
        <SequenceKeyHint keys={item.keys} />
    ) : (
        <KeyHint keys={item.keys} />
    );
}

function ShortcutsPage({ onBack }: { onBack: () => void }) {
    const [filter, setFilter] = useState('');
    const searchRef = useRef<HTMLInputElement>(null);
    useEffect(() => {
        searchRef.current?.focus();
    }, []);
    const groups = SHORTCUT_GROUPS.map((g) => ({
        title: g.title,
        items: fuzzyFilter(g.items, filter, (s) => [
            { text: s.label.toLowerCase(), weight: 1, fuzzy: true },
            { text: s.keys.join(' ').toLowerCase(), weight: 0.6, fuzzy: true },
        ]),
    })).filter((g) => g.items.length > 0);

    return (
        <div>
            {/* Single top row: a Back affordance, the search input, and an Esc hint
                — mirrors the root palette so the panel has just one divider. */}
            <div className={cn(SEARCH_ROW, 'pl-3')}>
                <button
                    type="button"
                    data-testid="command-palette-back"
                    onClick={onBack}
                    aria-label="Back"
                    className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-foreground/[0.06] text-foreground/80 transition-colors hover:bg-foreground/[0.1] hover:text-foreground"
                >
                    <ChevronLeft className="h-[18px] w-[18px]" />
                </button>
                <input
                    ref={searchRef}
                    value={filter}
                    onChange={(e) => setFilter(e.target.value)}
                    placeholder="Search shortcuts…"
                    className={SEARCH_INPUT}
                />
                <KeyHint keys={['esc']} />
            </div>
            <div className={LIST}>
                {groups.length === 0 ? (
                    <div className={EMPTY}>
                        No shortcuts for “{filter}”
                    </div>
                ) : (
                    groups.map((g) => (
                        <div key={g.title}>
                            <div data-cmd-section className={SECTION}>
                                {g.title}
                            </div>
                            {g.items.map((s) => (
                                <div
                                    key={s.label}
                                    className="flex h-10 items-center justify-between rounded-[14px] px-3"
                                >
                                    <span className="text-[14.5px] text-foreground/90">
                                        {s.label}
                                    </span>
                                    <ShortcutKeys item={s} />
                                </div>
                            ))}
                        </div>
                    ))
                )}
            </div>
        </div>
    );
}
