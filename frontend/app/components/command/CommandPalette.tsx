// Global, Linear-style command palette. Mounted once in the dashboard shell so
// it is available on every authenticated screen (browser, editor, settings,
// feed). Opens on ⌘K / Ctrl+K. Provides navigation (workflows, feed, every
// settings section), quick actions (new workflow / folder), jump-to-any-workflow
// fuzzy search, and account actions (toggle chat sidebar, keyboard shortcuts,
// sign out). It reads workflow data from the shared WorkflowBrowserDataProvider
// (no second data hook instance) and drives navigation via the existing URL /
// navigation conventions, so it adds no new state ownership.

import {
    useCallback,
    useEffect,
    useMemo,
    useRef,
    useState,
    type ComponentType,
} from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import {
    Search,
    LayoutGrid,
    UserCheck,
    Plus,
    FolderPlus,
    BarChart3,
    KeyRound,
    Building2,
    Globe,
    Brain,
    Code2,
    MessageCircle,
    Keyboard,
    LogOut,
    Sun,
    Moon,
    Monitor,
    Workflow as WorkflowIcon,
    CornerDownLeft,
    ChevronLeft,
    ArrowRight,
    LayoutDashboard,
} from 'lucide-react';
import { cn } from '~/lib/utils';
import { scoreFields } from '~/lib/fuzzyRank';
import { isTextEntryTarget } from '~/lib/keyboard';
import { useAnalytics } from '~/lib/analytics';
import { EVENTS } from '~/lib/analytics-events';
import {
    GOTO_DESTINATIONS,
    NEW_ACTIONS,
    OPEN_SCOPES,
    COMMAND_SHORTCUT_KEYS,
    OPEN_COMMAND_PALETTE_EVENT,
    type OpenCommandPaletteDetail,
    type PaletteScope,
} from '~/lib/shortcuts';
import { navigateToSettings, navigateToWorkflow, goToWorkflows, triggerBrowserAction, type SettingsSection, navigateToDashboard } from '~/lib/navigation';
import { sendEventAsync } from '~/lib/socket-sender';
import type { CredentialInfo } from '~/types/socket-events.generated';
import { NoClickMCPSetupModal } from '~/components/workflow/MCPConnectModal';
import { getCredentialIcon } from '~/utils/credentialIcons';
import { formatCredentialTypeLabel } from '~/utils/credentialTypes';
import { fuzzyFilter } from '~/utils/fuzzySearch';
import { BrandIcon } from '~/components/shared/BrandIcon';
import { openCreateCredential } from '~/components/shared/popups/CreateCredentialDialog';
import { relativeShort } from '~/components/workflow/WorkflowBrowserCards';
import { useCachedValtioState } from '~/hooks/useCachedValtioState';
import { useWorkflowBrowserDataContext } from '~/hooks/WorkflowBrowserDataProvider';
import { useListKeyboardNav } from '~/hooks/useListKeyboardNav';
import { useTheme } from '~/hooks/useTheme';
import type { Theme } from '~/lib/theme';
import { KeyHint, SequenceKeyHint } from '~/components/shared/KeyHint';
import { NodeIconStack } from '~/components/shared/NodeIconStack';
import { workflowIconTypes } from '~/lib/workflowBrowserStore';

type IconType = ComponentType<{ className?: string }>;
// 'Credentials' is intentionally absent from SECTION_ORDER: those rows only
// appear in the scoped ("O C") mode, never in the default browse list.
type Section =
    | 'Workflows'
    | 'Credentials'
    | 'Navigation'
    | 'Actions'
    | 'Open'
    | 'Setup'
    | 'Account';
// Actions (create) first, then Open (scoped "Open X…"), Navigation, then
// jump-to-workflow results capped so a long list doesn't bury the primary
// commands. When the query matches a workflow name the other sections go empty
// and drop out, so the matches still surface at the top. NOTE: 'Workflows' must
// stay in this list for the scoped-open mode (scope === 'Workflows') to render.
const SECTION_ORDER: Section[] = [
    'Actions',
    'Open',
    'Navigation',
    'Workflows',
    'Setup',
    'Account',
];

// Appearance options surfaced as Account commands (mirrors the NavBar avatar
// picker). Static metadata; the active marker is stamped at build time from the
// live theme. Selecting one calls setTheme and keeps the palette open so the
// change is visible and comparable in place.
const THEME_OPTIONS: {
    value: Theme;
    label: string;
    icon: IconType;
    keywords: string;
}[] = [
    { value: 'light', label: 'light', icon: Sun, keywords: 'bright day white appearance mode' },
    { value: 'dark', label: 'dark', icon: Moon, keywords: 'night black appearance mode' },
    { value: 'system', label: 'system', icon: Monitor, keywords: 'auto os default appearance mode' },
];

interface Cmd {
    id: string;
    label: string;
    section: Section;
    icon: IconType;
    /** Brand-icon color (Tailwind class or hex) — set for service/brand rows so
     * the icon keeps its brand color instead of the default muted gray. */
    iconColor?: string;
    /** Extra terms folded into fuzzy matching (not shown). */
    keywords?: string;
    /** Node types for the integration-logo stack (workflow rows). */
    nodeTypes?: string[];
    /** Trailing metadata line (e.g. "5 nodes · 2d ago" for workflow rows). */
    meta?: string;
    /** When true the palette stays open after running (e.g. opening a sub-page). */
    keepOpen?: boolean;
    perform: () => void;
}

const SETTINGS_SECTIONS: {
    section: SettingsSection;
    label: string;
    icon: IconType;
    /** Extra search terms so natural queries (e.g. "api keys") surface the section. */
    keywords?: string;
}[] = [
    {
        section: 'usage',
        label: 'Usage',
        icon: BarChart3,
        keywords: 'costs credits spend',
    },
    {
        section: 'credentials',
        label: 'Credentials',
        icon: KeyRound,
        keywords: 'connections oauth integrations accounts',
    },
    {
        section: 'organization',
        label: 'Organization',
        icon: Building2,
        keywords: 'members team workspace',
    },
    {
        section: 'skills',
        label: 'Skills',
        icon: Brain,
        keywords: 'agent context knowledge',
    },
    {
        section: 'developer',
        label: 'Developer',
        icon: Code2,
        keywords: 'api keys api key token sdk',
    },
];

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

export function CommandPalette() {
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
    // Credentials are loaded lazily — only when the Credentials scope ("O C") is
    // entered, so the common palette open doesn't pay for a credential:list fetch.
    const [credentials, setCredentials] = useState<CredentialInfo[]>([]);
    const [credentialsLoaded, setCredentialsLoaded] = useState(false);
    const inputRef = useRef<HTMLInputElement>(null);
    const listRef = useRef<HTMLDivElement>(null);
    const store = useWorkflowBrowserDataContext();
    const { loadAllWorkflows } = store;
    const [theme, setTheme] = useTheme();

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

    // Lazily load credentials the first time the Credentials scope is entered.
    useEffect(() => {
        if (scope !== 'Credentials' || credentialsLoaded) return;
        let cancelled = false;
        (async () => {
            const response = await sendEventAsync({
                event_name: 'credential:list',
                request_id: `palette-cred-list-${Date.now()}`,
            });
            if (cancelled) return;
            setCredentials((response?.credentials ?? []) as CredentialInfo[]);
            setCredentialsLoaded(true);
        })();
        return () => {
            cancelled = true;
        };
    }, [scope, credentialsLoaded]);

    // Reset transient state when closed; on open, force-refresh the full workflow
    // set once so jump-to-workflow shows current node counts / types (cached
    // entries can be stale). The ref guards against the effect re-firing when
    // loadAllWorkflows' identity changes (folderTree updates) mid-open.
    const refreshedThisOpenRef = useRef(false);
    useEffect(() => {
        if (!open) {
            setQuery('');
            setPage('root');
            setScope(null);
            setCredentialsLoaded(false);
            refreshedThisOpenRef.current = false;
        } else if (!refreshedThisOpenRef.current) {
            refreshedThisOpenRef.current = true;
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
            if (!cmd.keepOpen) close();
            cmd.perform();
        },
        [close]
    );

    // ── All workflows, deduped + most-recent first ─────────────────────────
    // Dedup is structural (getAllWorkflows dedups by id, own wins ties); we only
    // project + sort by recency here.
    const allWorkflows = useMemo(
        () =>
            store
                .getAllWorkflows()
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
        [store.getAllWorkflows],
    );

    // ── Command catalogue ──────────────────────────────────────────────────
    const allCommands = useMemo<Cmd[]>(() => {
        const signOut = async () => {
            await fetch('/dashboard', { method: 'POST', body: new FormData() });
            window.location.href = '/auth/login';
        };

        const workflowCmds: Cmd[] = allWorkflows.map((wf) => {
            const n = wf.node_count ?? 0;
            const rel = relativeShort(wf.updated_at);
            const meta = [`${n} ${n === 1 ? 'node' : 'nodes'}`, rel]
                .filter(Boolean)
                .join(' · ');
            return {
                id: `wf:${wf.id}`,
                label: `Open ${wf.name || 'Untitled'}`,
                section: 'Workflows',
                icon: WorkflowIcon,
                // Keep the bare name as a keyword so typing it still ranks as an
                // exact match despite the "Open " display prefix.
                keywords: wf.name || 'Untitled',
                nodeTypes: wf.node_types,
                meta,
                // Opens the flow synchronously (setSelectedWorkflow → FlowCanvas
                // mounts from cache) whether the browser is already mounted
                // (flow tab) or we're switching from another screen — no
                // navigate() → URL → useEffect round-trip. See navigateToWorkflow.
                perform: () =>
                    navigateToWorkflow({
                        id: wf.id,
                        name: wf.name || 'Untitled',
                    }),
            };
        });

        // Credential rows — only surfaced in the Credentials scope ("O C").
        // Selecting one opens the create-credential popup preselected to that
        // credential (the same popup as "Create new credential", but focused).
        const credentialCmds: Cmd[] = credentials.map((c) => {
            const { Icon, iconColor, hasServiceIcon } = getCredentialIcon(
                c.credential_type,
                c.metadata
            );
            const email =
                typeof c.metadata?.email === 'string' ? c.metadata.email : '';
            const meta = [
                formatCredentialTypeLabel(c.credential_type),
                relativeShort(c.created_at),
            ]
                .filter(Boolean)
                .join(' · ');
            return {
                id: `cred:${c.id}`,
                label: c.name,
                section: 'Credentials',
                icon: Icon,
                iconColor: iconColor || (hasServiceIcon ? 'text-foreground' : 'text-muted-foreground'),
                keywords: `${c.credential_type} ${email}`,
                meta,
                perform: () =>
                    openCreateCredential({
                        credentialType: c.credential_type,
                        credentialId: c.id,
                    }),
            };
        });

        const navCmds: Cmd[] = [
            {
                id: 'nav:workflows',
                label: 'Go to workflows',
                section: 'Navigation',
                icon: LayoutGrid,
                keywords: 'home browser flows',
                // Synchronous tab switch (same path as a NavBar click), not the
                // slower navigate() URL round-trip. Reset closes any open
                // workflow so we land on the browser.
                perform: goToWorkflows,
            },
            {
                id: 'nav:dashboard',
                label: 'Go to dashboard',
                section: 'Navigation',
                icon: LayoutDashboard,
                keywords: 'home overview feed runs agents files credentials',
                perform: () => navigateToDashboard(),
            },
            {
                id: 'nav:attention',
                label: 'Go to needs you',
                section: 'Navigation',
                icon: UserCheck,
                keywords: 'approvals feed notifications inbox questions',
                perform: () => navigateToDashboard('attention'),
            },
            ...SETTINGS_SECTIONS.map(
                (s): Cmd => ({
                    id: `nav:settings:${s.section}`,
                    label: `Go to ${s.label.toLowerCase()}`,
                    section: 'Navigation',
                    icon: s.icon,
                    keywords: `settings ${s.section} ${s.keywords ?? ''}`,
                    perform: () => navigateToSettings({ section: s.section }),
                })
            ),
        ];

        const setupCmds: Cmd[] = [
            {
                id: 'setup:noclick-mcp',
                label: 'Set up MCP…',
                section: 'Setup',
                icon: Globe,
                keywords: 'noclick mcp server connect claude cursor codex chatgpt windsurf zed model context protocol api setup install',
                // Per-client setup guides for the platform MCP server —
                // build/run workflows from any MCP client.
                perform: () => setMcpSetupOpen(true),
            },
        ];

        const actionCmds: Cmd[] = [
            {
                id: 'action:new-workflow',
                label: 'Create new workflow…',
                section: 'Actions',
                icon: Plus,
                keywords: 'new add blank',
                // Fires synchronously (creates + shows the spinner / opens the
                // dialog) from any screen — see triggerBrowserAction.
                perform: () => triggerBrowserAction('create'),
            },
            {
                id: 'action:new-folder',
                label: 'Create new folder…',
                section: 'Actions',
                icon: FolderPlus,
                keywords: 'new add directory',
                perform: () => triggerBrowserAction('new-folder'),
            },
            {
                id: 'action:new-credential',
                label: 'Create new credential…',
                section: 'Actions',
                icon: KeyRound,
                keywords: 'new add connect service oauth api key token integration account login',
                // Opens the global create-credential dialog over the current
                // screen (no forced navigation) — see GlobalCreateCredentialDialog.
                perform: () => openCreateCredential(),
            },
        ];

        // "Open X…" commands (one per O-shortcut). Selecting one switches the
        // palette into that scope (keepOpen) — the same mode "O <key>" opens.
        const openCmds: Cmd[] = OPEN_SCOPES.map((s): Cmd => ({
            id: s.commandId,
            label: s.label,
            section: 'Open',
            icon: WorkflowIcon,
            keywords: 'open jump search',
            keepOpen: true,
            perform: () => {
                setQuery('');
                setScope(s.scope);
            },
        }));

        const accountCmds: Cmd[] = [
            {
                id: 'account:toggle-chat',
                label: 'Toggle chat sidebar',
                section: 'Account',
                icon: MessageCircle,
                keywords: 'ai assistant agent copilot collapse expand panel',
                perform: () => setChatExpanded((p) => !p),
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
                    perform: () => setTheme(opt.value),
                })
            ),
            {
                id: 'account:shortcuts',
                label: 'Open keyboard shortcuts',
                section: 'Account',
                icon: Keyboard,
                keywords: 'keys help hotkeys',
                keepOpen: true,
                perform: () => setPage('shortcuts'),
            },
            {
                id: 'account:sign-out',
                label: 'Sign out',
                section: 'Account',
                icon: LogOut,
                keywords: 'log out logout exit',
                perform: signOut,
            },
        ];

        return [
            ...workflowCmds,
            ...credentialCmds,
            ...navCmds,
            ...actionCmds,
            ...openCmds,
            ...setupCmds,
            ...accountCmds,
        ];
    }, [allWorkflows, credentials, setChatExpanded, theme, setTheme]);

    // ── Filter + group ─────────────────────────────────────────────────────
    // Each section is scored independently, but a fixed section order would let
    // a weak (subsequence) match in an early section outrank a strong (substring)
    // match in a later one — e.g. "chat" surfacing "Create new credential" above
    // "Toggle chat sidebar". So when there's a query we reorder sections by their
    // best item score; the curated SECTION_ORDER applies only to the browse state.
    const { rows, flat } = useMemo(() => {
        const q = query.trim();
        // Scoped open ("O W") restricts the palette to one section and shows more
        // of it; the section header is then redundant and suppressed below.
        const visibleSections = scope ? [scope] : SECTION_ORDER;
        const sections = visibleSections.map((sec) => {
            const inSection = allCommands.filter((c) => c.section === sec);
            let items = inSection;
            let best = 0;
            if (q) {
                const scored = inSection
                    .map((c) => ({
                        c,
                        score: scoreFields(q, [c.label, c.keywords]),
                    }))
                    .filter(
                        (x): x is { c: Cmd; score: number } => x.score !== null
                    )
                    .sort((a, b) => a.score - b.score);
                items = scored.map((x) => x.c);
                best = scored.length ? scored[0].score : Infinity;
            }
            if (sec === 'Workflows') {
                items = items.slice(0, scope ? 50 : q ? 6 : 3);
            } else if (sec === 'Credentials') {
                items = items.slice(0, 50);
            }
            return { title: sec, items, best };
        }).filter((s) => s.items.length > 0);

        if (q) {
            // Stable within equal scores: SECTION_ORDER is the tiebreaker since
            // Array.prototype.sort is stable and we started in that order.
            sections.sort((a, b) => a.best - b.best);
        }

        const builtRows: (
            | { type: 'header'; title: string }
            | { type: 'item'; cmd: Cmd; index: number }
        )[] = [];
        const flatList: Cmd[] = [];
        for (const sec of sections) {
            if (!scope) builtRows.push({ type: 'header', title: sec.title });
            for (const cmd of sec.items) {
                builtRows.push({ type: 'item', cmd, index: flatList.length });
                flatList.push(cmd);
            }
        }
        return { rows: builtRows, flat: flatList };
    }, [allCommands, query, scope]);

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
        <Dialog.Root open={open} onOpenChange={setOpen}>
            <Dialog.Portal>
                <Dialog.Overlay className="fixed inset-0 z-[100] bg-black/40" />
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
                    // -translate-x-1/2 (a static transform, not animated).
                    className="fixed left-1/2 top-[12vh] z-[101] w-[92vw] max-w-3xl -translate-x-1/2 overflow-hidden rounded-xl border border-border dark:border-white/10 bg-background dark:bg-[#0a0a0b] shadow-2xl dark:shadow-black/60"
                >
                    <Dialog.Title className="sr-only">
                        Command palette
                    </Dialog.Title>

                    {page === 'root' ? (
                        <>
                            {/* Search — in a scope ("O W") the leading glyph becomes
                                the scope's icon (workflow) instead of the magnifier. */}
                            <div className="flex items-center gap-2.5 px-4 pt-1">
                                {scope === 'Workflows' ? (
                                    <WorkflowIcon className="h-4 w-4 shrink-0 text-muted-foreground" />
                                ) : scope === 'Credentials' ? (
                                    <KeyRound className="h-4 w-4 shrink-0 text-muted-foreground" />
                                ) : (
                                    <Search className="h-4 w-4 shrink-0 text-muted-foreground dark:text-zinc-500" />
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
                                            : 'Search workflows, settings, actions…'
                                    }
                                    className="h-12 w-full bg-transparent text-sm text-foreground placeholder:text-[hsl(var(--placeholder))] focus:outline-none"
                                />
                                <KeyHint keys={['esc']} />
                            </div>

                            {/* Results */}
                            <div
                                ref={listRef}
                                className="max-h-[38vh] overflow-y-auto scrollbar-subtle p-1.5"
                            >
                                {rows.length === 0 ? (
                                    <div className="px-3 py-8 text-center text-sm text-muted-foreground dark:text-zinc-500">
                                        {query
                                            ? `No results for “${query}”`
                                            : scope === 'Credentials'
                                              ? 'No credentials yet'
                                              : scope === 'Workflows'
                                                ? 'No workflows yet'
                                                : 'No results'}
                                    </div>
                                ) : (
                                    rows.map((row, i) =>
                                        row.type === 'header' ? (
                                            <div
                                                key={`h:${row.title}:${i}`}
                                                className="px-2.5 pb-1 pt-3 text-[11px] font-medium uppercase tracking-wide text-muted-foreground dark:text-zinc-500 first:pt-1.5"
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
                            <div className="flex items-center gap-4 border-t border-border dark:border-white/[0.06] px-4 py-2.5 text-[11px] text-muted-foreground dark:text-zinc-500">
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
    return (
        <button
            type="button"
            data-cmd-index={index}
            onMouseMove={onHover}
            onClick={onSelect}
            className={cn(
                'group flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-left transition-colors',
                active ? 'bg-foreground/[0.08]' : 'hover:bg-foreground/[0.04]'
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
                <Icon
                    className={cn(
                        'h-[18px] w-[18px] shrink-0',
                        active ? 'text-foreground/80' : 'text-muted-foreground dark:text-zinc-500'
                    )}
                />
            )}
            <span className="flex-1 truncate text-[13px] text-foreground">
                {cmd.label}
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
                    className="shrink-0"
                />
            )}
            {cmd.meta && (
                <span className="shrink-0 whitespace-nowrap text-[11px] text-muted-foreground dark:text-zinc-500">
                    {cmd.meta}
                </span>
            )}
            {/* Shortcut hint so people learn it in place: sequences as "G then U",
                combos (⌘/) as adjacent keycaps. */}
            {COMMAND_SHORTCUT_KEYS[cmd.id] &&
                (COMMAND_SHORTCUT_KEYS[cmd.id].sequence ? (
                    <SequenceKeyHint
                        keys={COMMAND_SHORTCUT_KEYS[cmd.id].keys}
                        className="shrink-0"
                    />
                ) : (
                    <KeyHint
                        keys={COMMAND_SHORTCUT_KEYS[cmd.id].keys}
                        className="shrink-0"
                    />
                ))}
            {cmd.section === 'Navigation' ? (
                <ArrowRight
                    className={cn(
                        'h-4 w-4 shrink-0',
                        active ? 'text-muted-foreground' : 'text-muted-foreground/70 dark:text-zinc-600'
                    )}
                />
            ) : (
                active && (
                    <CornerDownLeft className="h-3.5 w-3.5 shrink-0 text-muted-foreground dark:text-zinc-500" />
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
            <div className="flex items-center gap-2.5 px-4">
                <button
                    type="button"
                    data-testid="command-palette-back"
                    onClick={onBack}
                    aria-label="Back"
                    className="shrink-0 text-muted-foreground dark:text-zinc-500 hover:text-foreground"
                >
                    <ChevronLeft className="h-4 w-4" />
                </button>
                <input
                    ref={searchRef}
                    value={filter}
                    onChange={(e) => setFilter(e.target.value)}
                    placeholder="Search shortcuts…"
                    className="h-12 w-full bg-transparent text-sm text-foreground placeholder:text-[hsl(var(--placeholder))] focus:outline-none"
                />
                <KeyHint keys={['esc']} />
            </div>
            <div className="max-h-[38vh] overflow-y-auto scrollbar-subtle border-t border-border dark:border-white/[0.06] p-2">
                {groups.length === 0 ? (
                    <div className="px-3 py-8 text-center text-sm text-muted-foreground dark:text-zinc-500">
                        No shortcuts for “{filter}”
                    </div>
                ) : (
                    groups.map((g) => (
                        <div key={g.title}>
                            <div className="px-2.5 pb-1 pt-3 text-[11px] font-medium uppercase tracking-wide text-muted-foreground dark:text-zinc-500 first:pt-1.5">
                                {g.title}
                            </div>
                            {g.items.map((s) => (
                                <div
                                    key={s.label}
                                    className="flex items-center justify-between rounded-lg px-2.5 py-2"
                                >
                                    <span className="text-sm text-foreground/80">
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
