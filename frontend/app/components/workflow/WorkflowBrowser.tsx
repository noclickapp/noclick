import {
    useState,
    useCallback,
    useEffect,
    useLayoutEffect,
    useRef,
    useMemo,
    lazy,
    Suspense,
} from 'react';
import {
    consumePendingFlowIntent,
    type FlowIntent,
    type BrowserAction,
} from '~/lib/navigation';
import { Card } from '~/components/ui/card';
import {
    Plus,
    Workflow,
    Share2,
    Folder,
    FolderPlus,
    Home,
    PanelLeft,
    ExternalLink,
    LayoutGrid,
    List,
    Search,
    Users,
    User,
    UserPlus,
    ChevronDown,
    Loader2,
} from 'lucide-react';
import { SiClaude, SiOpenai } from 'react-icons/si';
import {
    VideoPopup,
    CopyableCode,
} from '~/components/shared/popups/VideoPopup';
import { useIsMobile } from '~/hooks/useIsMobile';
import { cn } from '~/lib/utils';
import { fuzzyFilter } from '~/utils/fuzzySearch';
import { isTextEntryTarget, isModalOpen } from '~/lib/keyboard';
import { ShortcutTooltip } from '~/components/shared/ShortcutTooltip';
import { useOrgContext } from '~/hooks/useOrgContext';
import {
    type WorkflowApp,
    type FolderInfoLocal,
} from '~/hooks/useWorkflowBrowserData';
import { useWorkflowBrowserDataContext } from '~/hooks/WorkflowBrowserDataProvider';
// Lazy-loaded so the workflow editor + the heavy node-component registry it pulls
// (~4.7MB) load only when a workflow is opened — not on the dashboard's initial
// (workflow-list) render. The list, command palette, and chat resolve node icons
// from the serialized icon singleton instead, so they no longer pull the registry.
const FlowCanvas = lazy(() => import('./FlowCanvas'));
import { Button } from '~/components/ui/button';
import { useNavigate, useLocation } from 'react-router';
import { sendEventWithCallback, sendEventAsync } from '~/lib/socket-sender';
import { useSocketConnection } from '~/hooks/useSocketConnection';
import { EditItemPopup } from '~/components/shared/popups/EditItemPopup';
import { DeleteConfirmPopup } from '~/components/shared/popups/DeleteConfirmPopup';
import { ShareDialog } from '~/components/shared/popups/ShareDialog';
import { ForkDialog } from '~/components/shared/popups/ForkDialog';
import { CreateFolderPopup } from '~/components/shared/popups/CreateFolderPopup';
import { UpgradePopup } from '~/components/utils/UpgradePopup';
import { mcpServerUrl } from '~/lib/hostedDefaults';
import { isPlanLimitError } from '~/lib/planLimitErrors';
import { FolderTreeSidebarArborist } from './FolderTreeSidebarArborist';
import { FolderBreadcrumbs } from './FolderBreadcrumbs';
import { useGridSelection } from '~/hooks/useGridSelection';
import { useWorkflowBrowserDrag } from '~/hooks/useWorkflowBrowserDrag';
import { DndContext, pointerWithin } from '@dnd-kit/core';
import { WorkflowBrowserDragOverlay } from './WorkflowBrowserDragOverlay';
import {
    WorkflowCardSkeleton,
    DroppableHeaderBar,
    FolderCard,
    WorkflowCard,
} from './WorkflowBrowserCards';
import { FolderRow, WorkflowRow } from './WorkflowBrowserList';
import { useCachedValtioState } from '~/hooks/useCachedValtioState';
import { KeyHint } from '~/components/shared/KeyHint';
import { useListKeyboardNav } from '~/hooks/useListKeyboardNav';
import { TrashView } from './TrashView';
import {
    DropdownMenu,
    DropdownMenuTrigger,
    DropdownMenuContent,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
} from '~/components/ui/dropdown-menu';
import {
    WorkflowUpdateRequest,
    WorkflowDeleteRequest,
    ShareLeaveRequest,
    FolderDeleteRequest,
    FolderUpdateRequest,
    WorkflowCreateRequest,
    ResourceForkRequest,
    ShareInviteAcceptRequest,
    OnboardingSkipRequest,
    type FolderCreateResponse,
} from '~/types/socket-events.generated';
import { PENDING_INVITE_KEY } from '~/lib/inviteLink';
import { SCAFFOLD_DATA_KEY, PENDING_SCAFFOLD_KEY } from '~/lib/agentScaffold';
import {
    hasPendingDeferredOpen,
    clearPostOnboardingFlow,
    FORK_DATA_KEY,
    HERO_PROMPT_KEY,
    POST_ONBOARDING_FLOW_KEY,
} from '~/lib/deferredOpen';
import { useAnalytics } from '~/lib/analytics';
import { EVENTS } from '~/lib/analytics-events';

// The small custom Claude Code glyph used in the connect-integration row below.
// Lives inline because it's only used here and doesn't belong in a shared icons lib.
const ClaudeCodeIcon = ({ className }: { className?: string }) => (
    <svg
        xmlns="http://www.w3.org/2000/svg"
        viewBox="0 0 294 224"
        className={className}
    >
        <path
            d="M 63.5,47.5 C 119.5,47.5 175.5,47.5 231.5,47.5C 231.5,67.1667 231.5,86.8333 231.5,106.5C 240.833,106.5 250.167,106.5 259.5,106.5C 259.5,116.5 259.5,126.5 259.5,136.5C 250.167,136.5 240.833,136.5 231.5,136.5C 231.5,146.5 231.5,156.5 231.5,166.5C 226.833,166.5 222.167,166.5 217.5,166.5C 217.5,176.5 217.5,186.5 217.5,196.5C 212.833,196.5 208.167,196.5 203.5,196.5C 203.5,186.5 203.5,176.5 203.5,166.5C 198.833,166.5 194.167,166.5 189.5,166.5C 189.5,176.5 189.5,186.5 189.5,196.5C 184.833,196.5 180.167,196.5 175.5,196.5C 175.5,186.5 175.5,176.5 175.5,166.5C 156.833,166.5 138.167,166.5 119.5,166.5C 119.5,176.5 119.5,186.5 119.5,196.5C 114.833,196.5 110.167,196.5 105.5,196.5C 105.5,186.5 105.5,176.5 105.5,166.5C 100.833,166.5 96.1667,166.5 91.5,166.5C 91.5,176.5 91.5,186.5 91.5,196.5C 86.8333,196.5 82.1667,196.5 77.5,196.5C 77.5,186.5 77.5,176.5 77.5,166.5C 72.8333,166.5 68.1667,166.5 63.5,166.5C 63.5,156.5 63.5,146.5 63.5,136.5C 54.1667,136.5 44.8333,136.5 35.5,136.5C 35.5,126.5 35.5,116.5 35.5,106.5C 44.8333,106.5 54.1667,106.5 63.5,106.5C 63.5,86.8333 63.5,67.1667 63.5,47.5 Z"
            fill="currentColor"
            fillRule="evenodd"
        />
        <path
            d="M 91.5,77.5 H 105.5 V 106.5 H 91.5 Z"
            className="fill-background"
        />
        <path
            d="M 189.5,77.5 H 203.5 V 106.5 H 189.5 Z"
            className="fill-background"
        />
    </svg>
);

type BrowserLayoutMode = 'grid' | 'list';

// Segmented grid/list toggle shown in the browser header. Switches how the
// current folder's contents render (cards vs. compact rows); the choice is
// persisted per browser via useCachedValtioState.
function LayoutToggle({
    mode,
    onChange,
}: {
    mode: BrowserLayoutMode;
    onChange: (mode: BrowserLayoutMode) => void;
}) {
    return (
        <div className="flex items-center gap-0.5 p-0.5 rounded-full bg-accent dark:bg-secondary/60 border border-border dark:border-zinc-700/50 flex-shrink-0">
            <ShortcutTooltip label="Card view" keys={['C']} sideOffset={7}>
                <button
                    onClick={() => onChange('grid')}
                    aria-label="Card view"
                    aria-pressed={mode === 'grid'}
                    className={cn(
                        'p-1.5 rounded-full transition-colors',
                        mode === 'grid'
                            ? 'bg-card shadow-sm text-foreground dark:bg-muted-foreground/30 dark:shadow-none'
                            : 'text-muted-foreground hover:text-foreground'
                    )}
                >
                    <LayoutGrid className="w-3.5 h-3.5" />
                </button>
            </ShortcutTooltip>
            <ShortcutTooltip label="List view" keys={['L']} sideOffset={7}>
                <button
                    onClick={() => onChange('list')}
                    aria-label="List view"
                    aria-pressed={mode === 'list'}
                    className={cn(
                        'p-1.5 rounded-full transition-colors',
                        mode === 'list'
                            ? 'bg-card shadow-sm text-foreground dark:bg-muted-foreground/30 dark:shadow-none'
                            : 'text-muted-foreground hover:text-foreground'
                    )}
                >
                    <List className="w-3.5 h-3.5" />
                </button>
            </ShortcutTooltip>
        </div>
    );
}

// Primary "create workflow" action in the header bar. Lives here (not just the
// grid's empty-state card) so list view also has a discoverable way to create.
function NewWorkflowButton({
    onClick,
    isCreating,
}: {
    onClick: () => void;
    isCreating: boolean;
}) {
    return (
        <ShortcutTooltip keys={['N', 'W']}>
            <button
                onClick={() => {
                    if (!isCreating) onClick();
                }}
                disabled={isCreating}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-primary text-primary-foreground hover:bg-primary/90 transition-colors flex-shrink-0 text-xs font-medium disabled:opacity-60"
            >
                {isCreating ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                    <Plus className="w-3.5 h-3.5" strokeWidth={2.5} />
                )}
                New Workflow
            </button>
        </ShortcutTooltip>
    );
}

// Ownership filter for the browser. Folds the old "Shared with me" view into the
// main grid/list: the workflow:list response already returns both owned and
// shared items (with is_owner set), so this is a pure client-side filter rather
// than a separate fetch. Persisted per browser via useCachedValtioState.
type OwnershipFilter = 'all' | 'owned' | 'not_owned';

const OWNERSHIP_OPTIONS: {
    value: OwnershipFilter;
    label: string;
    icon: typeof Users;
}[] = [
    { value: 'all', label: 'Owned by anyone', icon: Users },
    { value: 'owned', label: 'Owned by me', icon: User },
    { value: 'not_owned', label: 'Not owned by me', icon: UserPlus },
];

function OwnershipFilterDropdown({
    value,
    onChange,
}: {
    value: OwnershipFilter;
    onChange: (value: OwnershipFilter) => void;
}) {
    const active =
        OWNERSHIP_OPTIONS.find((o) => o.value === value) ??
        OWNERSHIP_OPTIONS[0];
    const ActiveIcon = active.icon;
    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <button
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-card dark:bg-secondary/60 border border-border dark:border-zinc-700/50 hover:border-muted-foreground/40 dark:hover:border-zinc-600/50 hover:bg-muted dark:hover:bg-secondary transition-colors flex-shrink-0 outline-none focus:outline-none focus-visible:outline-none"
                    title="Filter by ownership"
                >
                    <ActiveIcon className="w-3.5 h-3.5 text-muted-foreground" />
                    <span className="text-xs text-muted-foreground hidden sm:inline">
                        {active.label}
                    </span>
                    <ChevronDown className="w-3 h-3 text-muted-foreground dark:text-zinc-500" />
                </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent
                align="end"
                className="bg-card border-border text-foreground"
            >
                <DropdownMenuRadioGroup
                    value={value}
                    onValueChange={(v) => onChange(v as OwnershipFilter)}
                >
                    {OWNERSHIP_OPTIONS.map((o) => {
                        const Icon = o.icon;
                        return (
                            <DropdownMenuRadioItem
                                key={o.value}
                                value={o.value}
                                className="text-xs gap-2 cursor-pointer transition-none focus:bg-accent focus:text-foreground"
                            >
                                <Icon className="w-3.5 h-3.5 text-muted-foreground" />
                                {o.label}
                            </DropdownMenuRadioItem>
                        );
                    })}
                </DropdownMenuRadioGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    );
}

type ConnectIntegrationType = 'claude' | 'claude-code' | 'chatgpt';

interface ConnectIntegration {
    type: ConnectIntegrationType;
    title: string;
    url: string;
    Icon: React.ComponentType<{ className?: string }>;
    iconClassName: string;
}

const CONNECT_INTEGRATIONS: ConnectIntegration[] = [
    {
        type: 'claude',
        title: 'Connect to Claude',
        url: 'https://youtu.be/lBVY96kEv2c',
        Icon: SiClaude,
        iconClassName: 'w-3.5 h-3.5',
    },
    {
        type: 'claude-code',
        title: 'Connect to Claude Code',
        url: 'https://youtu.be/o3OlH9X_8Go',
        Icon: ClaudeCodeIcon,
        iconClassName: 'h-[1.125rem] w-auto -my-0.5',
    },
    {
        type: 'chatgpt',
        title: 'Connect to ChatGPT',
        url: 'https://youtu.be/b__nr5zP9i0',
        Icon: SiOpenai,
        iconClassName: 'w-3.5 h-3.5',
    },
];

interface WorkflowBrowserProps {
    scopeId: string;
    onActiveWorkflowChange?: (workflowId: string | null) => void;
    /** Workflow ID to select on mount (from URL param) */
    initialWorkflowId?: string | null;
}

type FolderInfo = FolderInfoLocal;
type ViewMode = 'grid' | 'trash';

// Modal dialogs are mutually exclusive (opening one auto-closes any other), so
// they share a single tagged state rather than 8 separate booleans/objects.
type Dialog =
    | { kind: 'none' }
    | { kind: 'editWorkflow'; workflow: WorkflowApp }
    | { kind: 'editFolder'; folder: FolderInfo }
    | { kind: 'deleteWorkflow'; workflowId: string }
    | { kind: 'deleteFolder'; id: string; name: string }
    | { kind: 'shareWorkflow'; workflow: WorkflowApp }
    | { kind: 'shareFolder'; id: string; name: string }
    | { kind: 'forkWorkflow'; workflow: WorkflowApp }
    | { kind: 'createFolder' };

export function WorkflowBrowser({
    scopeId,
    onActiveWorkflowChange,
    initialWorkflowId,
}: WorkflowBrowserProps) {
    const navigate = useNavigate();
    const location = useLocation();
    const [orgContext] = useOrgContext();
    const { logActivity } = useAnalytics();

    // Unified store for folders + workflows (IndexedDB-cached, shared with sidebar
    // and the global command palette via WorkflowBrowserDataProvider).
    const store = useWorkflowBrowserDataContext();
    const [connectVideo, setConnectVideo] = useState<{
        title: string;
        url: string;
        type: 'claude' | 'claude-code' | 'chatgpt';
    } | null>(null);

    const [selectedWorkflow, setSelectedWorkflow] =
        useState<WorkflowApp | null>(null);
    const [pendingWorkflowSelect, setPendingWorkflowSelect] = useState<
        string | null
    >(null);
    const [pendingBackNavigation, setPendingBackNavigation] = useState(false);
    const [selectedFolderId, setSelectedFolderIdRaw] = useState<string | null>(
        null
    );
    const [viewMode, setViewMode] = useState<ViewMode>('grid');
    // Card grid vs. compact list layout for the browser. Persisted per browser
    // (IndexedDB, no Redis) since it's a local UI preference, not shared state.
    const [layoutMode, setLayoutMode] = useCachedValtioState<BrowserLayoutMode>(
        scopeId,
        'browserLayoutMode',
        'grid',
        true
    );
    // Ownership filter (anyone / owned by me / shared with me). Persisted per
    // browser, same as layoutMode — it's a local view preference, not shared.
    const [ownershipFilter, setOwnershipFilter] =
        useCachedValtioState<OwnershipFilter>(
            scopeId,
            'browserOwnershipFilter',
            'all',
            true
        );
    // Filters the list view (folders + workflows by name). Session-only.
    const [listSearch, setListSearch] = useState('');
    const searchInputRef = useRef<HTMLInputElement>(null);
    const listContainerRef = useRef<HTMLDivElement>(null);
    // Wrap setSelectedFolderId to drop back to grid view when navigating folders
    const setSelectedFolderId = useCallback((folderId: string | null) => {
        setSelectedFolderIdRaw(folderId);
        setViewMode('grid');
    }, []);
    // Reset browser navigation to the new workspace's root when the scope
    // (scopeId = org-scoped browser path) changes. selectedFolderId/viewMode/
    // listSearch are session-only useState that don't reset without a remount,
    // so after an org switch they'd keep pointing at the PREVIOUS org's folder
    // (which doesn't exist in the new org) — pairing the freshly-resynced store
    // data with a stale folder id shows an empty folder + broken breadcrumbs.
    // Done in render (these fields have no URL/effect antagonist) so the first
    // painted frame is already the new org's root. An open workflow is entangled
    // with the ?workflow URL param, so it's closed in the effect below instead.
    const browserScopeRenderRef = useRef(scopeId);
    if (browserScopeRenderRef.current !== scopeId) {
        browserScopeRenderRef.current = scopeId;
        setSelectedFolderIdRaw(null);
        setViewMode('grid');
        setListSearch('');
    }
    // Derive current view's folders and workflows from the unified store
    const currentFolders = store.getSubfolders(selectedFolderId);
    const workflows = store.getWorkflows(selectedFolderId);
    const loadingWorkflows =
        store.loadingWorkflows[selectedFolderId ?? ''] ?? false;
    // Ownership predicate: backend always sets is_owner, so anything not
    // explicitly false counts as owned. Reused by the grid, the list, and the
    // global-search branch so every surface filters identically.
    const matchesOwnership = useCallback(
        (isOwner: boolean | undefined) => {
            if (ownershipFilter === 'owned') return isOwner !== false;
            if (ownershipFilter === 'not_owned') return isOwner === false;
            return true;
        },
        [ownershipFilter]
    );
    const filteredFolders = useMemo(
        () => currentFolders.filter((f) => matchesOwnership(f.is_owner)),
        [currentFolders, matchesOwnership]
    );
    const filteredWorkflows = useMemo(
        () => (workflows || []).filter((w) => matchesOwnership(w.is_owner)),
        [workflows, matchesOwnership]
    );
    // Captured at mount: OnboardingQuestionnaire sets this flag to open a fresh workflow
    // automatically after finishing the questionnaire. Read synchronously so we can block
    // the browser grid from flashing before the workflow is created.
    const postOnboardingPendingRef = useRef<boolean>(
        typeof window !== 'undefined' &&
            sessionStorage.getItem(POST_ONBOARDING_FLOW_KEY) === 'true'
    );
    const [isCreatingWorkflow, setIsCreatingWorkflow] = useState(
        postOnboardingPendingRef.current
    );
    const [planLimitError, setPlanLimitError] = useState<string | null>(null);
    const [dialog, setDialog] = useState<Dialog>({ kind: 'none' });
    const closeDialog = useCallback(() => setDialog({ kind: 'none' }), []);
    const [sidebarCollapsed, setSidebarCollapsed] = useState(true);
    // Browser key shortcuts: "[" toggles the workspace/folder sidebar (mirrors
    // "/" for chat); "C" / "L" switch card/list view — but only on the grid, since
    // with a workflow open those keys belong to the canvas (C = nothing, L = logs).
    // Ignored while typing or when a modal (palette/dialog) is open.
    useEffect(() => {
        const onKey = (e: KeyboardEvent) => {
            if (e.metaKey || e.ctrlKey || e.altKey) return;
            if (isTextEntryTarget(e.target)) return;
            if (isModalOpen()) return;
            if (e.key === '[') {
                e.preventDefault();
                setSidebarCollapsed((c) => !c);
            } else if (!selectedWorkflow && (e.key === 'c' || e.key === 'C')) {
                e.preventDefault();
                setLayoutMode('grid');
            } else if (!selectedWorkflow && (e.key === 'l' || e.key === 'L')) {
                e.preventDefault();
                setLayoutMode('list');
            }
        };
        document.addEventListener('keydown', onKey);
        return () => document.removeEventListener('keydown', onKey);
    }, [setLayoutMode, selectedWorkflow]);
    const isMobile = useIsMobile();
    const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
    const [creatingFolder, setCreatingFolder] = useState(false);

    // Stable key for FlowCanvas - persists during temp→real ID swaps to prevent remounting
    const flowCanvasKeyRef = useRef<string | null>(null);

    // List view merges folders + workflows into one list sorted by last-edited
    // (most recent first; items without a timestamp sort last, then by name),
    // optionally filtered by the search box. `kind` drives row rendering. With a
    // search query the list goes GLOBAL — it searches folders + workflows across
    // the whole tree (any depth), each tagged with its parent `location`.
    const listItems = useMemo(() => {
        type ListItem =
            | {
                  kind: 'folder';
                  id: string;
                  name: string;
                  updated_at?: string;
                  folder: FolderInfo;
                  location?: string;
              }
            | {
                  kind: 'workflow';
                  id: string;
                  name: string;
                  updated_at?: string;
                  workflow: WorkflowApp;
                  location?: string;
              };
        const q = listSearch.trim().toLowerCase();

        let items: ListItem[];
        if (q) {
            const allFolders = store.getAllFolders();
            const folderNameById = new Map(
                allFolders.map((f) => [f.id, f.name])
            );
            const locationOf = (folderId: string | null | undefined) =>
                !folderId ? 'All Workflows' : folderNameById.get(folderId);
            const folderItems: ListItem[] = allFolders
                .filter((f) => matchesOwnership(f.is_owner))
                .map((f) => ({
                    kind: 'folder',
                    id: f.id,
                    name: f.name,
                    updated_at: f.updated_at,
                    folder: f,
                    location: locationOf(f.parent_folder_id),
                }));
            const ownEntries = Object.entries(store.workflowsByFolder).flatMap(
                ([fid, wfs]) =>
                    (wfs || []).map((w) => ({
                        w,
                        location: locationOf(fid || null),
                    }))
            );
            const ownWfIds = new Set(ownEntries.map((e) => e.w.id));
            // Shared-with-me workflows live at the root; dedup against any already
            // returned by workflow:list so global search shows each once.
            const sharedEntries = store.sharedWorkflows
                .filter((w) => !ownWfIds.has(w.id))
                .map((w) => ({ w, location: locationOf(null) }));
            const workflowItems: ListItem[] = [...ownEntries, ...sharedEntries]
                .filter(({ w }) => matchesOwnership(w.is_owner))
                .map(({ w, location }) => ({
                    kind: 'workflow' as const,
                    id: w.id,
                    name: w.name,
                    updated_at: w.updated_at,
                    workflow: w,
                    location,
                }));
            items = fuzzyFilter(
                [...folderItems, ...workflowItems],
                listSearch,
                (it) => [{ text: it.name.toLowerCase(), weight: 1, fuzzy: true }]
            );
        } else {
            items = [
                ...filteredFolders.map((f) => ({
                    kind: 'folder' as const,
                    id: f.id,
                    name: f.name,
                    updated_at: f.updated_at,
                    folder: f,
                })),
                ...filteredWorkflows.map((w) => ({
                    kind: 'workflow' as const,
                    id: w.id,
                    name: w.name,
                    updated_at: w.updated_at,
                    workflow: w,
                })),
            ];
        }
        return items.sort((a, b) => {
            const ta = a.updated_at ? Date.parse(a.updated_at) : 0;
            const tb = b.updated_at ? Date.parse(b.updated_at) : 0;
            if (tb !== ta) return tb - ta;
            return a.name.localeCompare(b.name);
        });
    }, [
        filteredFolders,
        filteredWorkflows,
        listSearch,
        store,
        matchesOwnership,
    ]);

    // Multi-select for drag-and-drop. Selection items must follow the on-screen
    // order so Shift+click range selection works: list view uses the merged/
    // sorted/filtered order; grid view keeps folders-then-workflows.
    const orderedItems = useMemo(
        () =>
            layoutMode === 'list'
                ? listItems.map((it) => ({ id: it.id }))
                : [
                      ...filteredFolders.map((f) => ({ id: f.id })),
                      ...filteredWorkflows.map((w) => ({ id: w.id })),
                  ],
        [layoutMode, listItems, filteredFolders, filteredWorkflows]
    );
    const selection = useGridSelection({ items: orderedItems });

    // Clear multi-select + search when navigating folders (so a folder opened
    // from a global-search result shows its contents, not the search results)
    useEffect(() => {
        selection.clearSelection();
        setListSearch('');
    }, [selectedFolderId]);

    // Clear multi-select when the ownership filter or layout changes: both alter
    // the visible set and/or its ordering, so a stale selection can orphan a
    // now-hidden ID (e.g. a not-owned flow when switching to "Owned by me") or
    // leave a confusing cross-layout shift-range anchor. clearSelection is stable.
    useEffect(() => {
        selection.clearSelection();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [ownershipFilter, layoutMode]);

    // While searching, pull every folder's workflows so global search can reach
    // nested items. loadAllWorkflows is a no-op for already-loaded folders, and
    // its identity changes when folderTree changes — so this re-runs (and picks
    // up newly-loaded folders) if the tree resolves/changes mid-search.
    const { loadAllWorkflows } = store;
    useEffect(() => {
        if (listSearch.trim()) loadAllWorkflows();
    }, [listSearch, loadAllWorkflows]);

    const drag = useWorkflowBrowserDrag({
        store,
        selection,
        currentFolders,
        workflows: workflows || [],
    });

    // Effect to inform parent about active workflow changes
    useEffect(() => {
        if (onActiveWorkflowChange) {
            onActiveWorkflowChange(
                selectedWorkflow ? selectedWorkflow.id : null
            );
        }
    }, [selectedWorkflow, onActiveWorkflowChange]);

    // Handle initialWorkflowId prop (from URL navigation via MCP)
    const initialWorkflowHandledRef = useRef(false);
    useEffect(() => {
        if (
            initialWorkflowId &&
            !initialWorkflowHandledRef.current &&
            workflows.length > 0
        ) {
            initialWorkflowHandledRef.current = true;
            const found = workflows.find((w) => w.id === initialWorkflowId);
            if (found) {
                setSelectedWorkflow(found);
            } else {
                // Workflow not in list yet - set placeholder
                setSelectedWorkflow({
                    id: initialWorkflowId,
                    name: 'Loading...',
                    description: '',
                });
            }
        }
    }, [initialWorkflowId, workflows]);

    // URL Syncing for selected workflow (URL → State)
    useEffect(() => {
        const params = new URLSearchParams(location.search);
        const workflowId = params.get('workflow');
        if (pendingBackNavigation) {
            if (!workflowId) setPendingBackNavigation(false);
            return;
        }
        if (!workflowId && !selectedWorkflow) {
            return;
        }

        // Skip if URL has a temp ID that's no longer in workflows
        // (This happens during temp→real transition - we wait for URL update effect to fix it)
        if (
            workflowId?.startsWith('temp-') &&
            !(workflows || []).some((w) => w.id === workflowId)
        ) {
            return;
        }

        const found = workflowId
            ? (workflows || []).find((w: WorkflowApp) => w.id === workflowId)
            : null;
        if (pendingWorkflowSelect && found?.id === pendingWorkflowSelect) {
            setPendingWorkflowSelect(null);
            return;
        }
        // If URL has a workflow ID but it's not found in the list:
        // - If we already have that workflow selected, keep it (don't unmount FlowCanvas)
        // - If we don't have it selected, create a placeholder so FlowCanvas can mount and fetch the data
        // This handles freshly forked workflows that haven't appeared in the list yet
        if (workflowId && !found) {
            if (selectedWorkflow?.id === workflowId) {
                // Already selected, keep it
                return;
            }
            // Create a placeholder workflow entry so FlowCanvas can mount
            // FlowCanvas will fetch the real data from the backend
            const placeholderWorkflow: WorkflowApp = {
                id: workflowId,
                name: 'Loading...',
                description: '',
                is_owner: true,
                user_permission: 'edit',
            };
            setSelectedWorkflow(placeholderWorkflow);
            return;
        }
        if (!pendingWorkflowSelect && found?.id !== selectedWorkflow?.id) {
            setSelectedWorkflow(found || null);
        }
    }, [
        location.search,
        workflows,
        pendingWorkflowSelect,
        pendingBackNavigation,
        selectedWorkflow,
    ]);

    // URL update for temp→real ID transition (State → URL)
    // Runs after state is settled, updates URL to match selectedWorkflow
    useEffect(() => {
        if (!selectedWorkflow || selectedWorkflow.id.startsWith('temp-')) {
            return;
        }
        const params = new URLSearchParams(location.search);
        const urlWorkflowId = params.get('workflow');
        // If URL has temp ID but selectedWorkflow has real ID, update URL
        if (urlWorkflowId?.startsWith('temp-')) {
            const newParams = new URLSearchParams(location.search);
            newParams.set('tab', 'workflows');
            newParams.set('workflow', selectedWorkflow.id);
            navigate(`?${newParams.toString()}`, { replace: true });
        }
    }, [selectedWorkflow, location.search, navigate]);

    // Clean up stale ?action=fork URL param. The fork itself is driven by the
    // noclick_fork_workflow_data sessionStorage key that PublicWorkflowView writes
    // right before redirecting to the dashboard.
    useEffect(() => {
        const params = new URLSearchParams(location.search);
        if (params.get('action') === 'fork') {
            const newParams = new URLSearchParams(location.search);
            newParams.delete('action');
            navigate(`?${newParams.toString()}`, { replace: true });
        }
    }, [location.search, navigate]);

    // Build the URL params for showing workflow <id> on the workflows tab.
    // Drops settings-only params so opening/creating a flow from another screen
    // (e.g. the usage dashboard) doesn't leave a stale ?section=/?orgTab= behind.
    const buildWorkflowParams = useCallback(
        (workflowId: string) => {
            const params = new URLSearchParams(location.search);
            params.set('tab', 'workflows');
            params.set('workflow', workflowId);
            params.delete('section');
            params.delete('orgTab');
            return params;
        },
        [location.search]
    );

    const handleWorkflowSelect = useCallback(
        (workflow: WorkflowApp) => {
            setSelectedWorkflow(workflow);
            setPendingWorkflowSelect(workflow.id);
            const newParams = buildWorkflowParams(workflow.id);
            setTimeout(() => navigate(`?${newParams.toString()}`), 0);
        },
        [navigate, buildWorkflowParams]
    );

    const isSearching = listSearch.trim().length > 0;
    // True while a global search is still pulling not-yet-loaded folders'
    // workflows (loadAllWorkflows fetches each own folder). Used to show skeletons
    // instead of a premature "no results". Keys off own-folder load state — shared
    // folders never load into workflowsByFolder, so checking them would keep this
    // true forever for anyone with a shared folder.
    const searchResolving = isSearching && !store.allWorkflowsLoaded;

    // Keyboard navigation for the list search (↑/↓ move, ↵ opens, Esc clears) —
    // shared with the sidebar via useListKeyboardNav.
    const {
        index: highlightedIndex,
        setIndex: setHighlightedIndex,
        handleKeyDown: handleSearchKeyDown,
    } = useListKeyboardNav({
        count: listItems.length,
        active: isSearching,
        onSelect: (i) => {
            const item = listItems[i];
            if (!item) return;
            if (item.kind === 'folder') setSelectedFolderId(item.id);
            else handleWorkflowSelect(item.workflow);
        },
        onEscape: () => {
            setListSearch('');
            searchInputRef.current?.blur();
        },
    });

    // Reset the highlight to the top whenever the result set changes.
    useEffect(() => {
        setHighlightedIndex(0);
    }, [listSearch, setHighlightedIndex]);

    // Keep the highlighted row scrolled into view (rows render in listItems order).
    useEffect(() => {
        if (!isSearching) return;
        const rows = listContainerRef.current?.querySelectorAll(
            '[data-workflow-card],[data-folder-card]'
        );
        (rows?.[highlightedIndex] as HTMLElement | undefined)?.scrollIntoView({
            block: 'nearest',
        });
    }, [highlightedIndex, isSearching]);

    const handleBackFromFlowCanvas = useCallback(() => {
        // No need to dispatch a chat-clear event: useConversation
        // observes WorkflowProvider unmount via useActiveWorkflowEditorId
        // and re-projects on the next mount. The previous conversation
        // is preserved server-side and auto-restored next time the user
        // opens this workflow.
        setSelectedWorkflow(null);
        setPendingBackNavigation(true);
        setPendingWorkflowSelect(null);
        const newParams = new URLSearchParams(location.search);
        newParams.set('tab', 'workflows');
        newParams.delete('workflow');
        setTimeout(() => navigate(`?${newParams.toString()}`), 0);
    }, [navigate, location.search]);

    // Refresh the shared-with-me list AND the current folder's workflow list
    // whenever we return to the grid from an open flow. Shared: covers a
    // just-joined invite flow (the share row is created while we're in FlowCanvas)
    // and any share made while the user was inside a workflow. Workflow list: the
    // card graph previews are projected from workflow:list's graph blob, so edits
    // made on the canvas only show up on the card after a refetch. One
    // latest-values closure ref so the effect keys on the transition alone.
    const onReturnToGridRef = useRef(() => {});
    onReturnToGridRef.current = () => {
        store.refreshSharedWorkflows();
        store.fetchWorkflows(selectedFolderId);
    };
    const prevSelectedWorkflowRef = useRef(selectedWorkflow);
    useEffect(() => {
        const had = prevSelectedWorkflowRef.current;
        prevSelectedWorkflowRef.current = selectedWorkflow;
        if (had && !selectedWorkflow) onReturnToGridRef.current();
    }, [selectedWorkflow]);

    // Listen for reset event from navbar "Workflows" click / "G W" - reuse back
    // button logic, and also drop out of the Trash system view back to the
    // workflow grid (Home) so "Go to workflows" works from any view.
    useEffect(() => {
        const handleReset = () => {
            if (selectedWorkflow) {
                flowCanvasKeyRef.current = null;
                handleBackFromFlowCanvas();
            } else if (viewMode !== 'grid') {
                setViewMode('grid');
                setSelectedFolderIdRaw(null);
            }
        };
        window.addEventListener('noclick:workflow-browser-reset', handleReset);
        return () =>
            window.removeEventListener(
                'noclick:workflow-browser-reset',
                handleReset
            );
    }, [selectedWorkflow, handleBackFromFlowCanvas, viewMode]);

    // Close any open workflow when the workspace scope (scopeId) changes:
    // the open flow belongs to the PREVIOUS org, and its ?workflow URL param
    // would otherwise be re-selected as a cross-org placeholder by the URL→state
    // effect. Reuse the tested back-navigation path (clears ?workflow, sets
    // pendingBackNavigation so that effect can't re-select the stale id). Deps are
    // [scopeId] only, so the effect re-creates solely on a scope change and
    // reads selectedWorkflow/handler from that render's closure (the switch
    // render, where the previous org's workflow is still open). The render-time
    // guard above already reset folder/view/search for the grid case.
    const browserScopeEffectRef = useRef(scopeId);
    useEffect(() => {
        if (browserScopeEffectRef.current === scopeId) return;
        browserScopeEffectRef.current = scopeId;
        if (selectedWorkflow) {
            flowCanvasKeyRef.current = null;
            handleBackFromFlowCanvas();
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps -- fire only on scope change
    }, [scopeId]);

    // Shared: commit a newly-created/forked workflow to local state + URL so FlowCanvas mounts.
    const commitNewWorkflow = useCallback(
        (newWorkflow: { id: string; name: string; description: string }) => {
            const workflowApp: WorkflowApp = {
                id: newWorkflow.id,
                name: newWorkflow.name,
                description: newWorkflow.description,
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
                is_owner: true,
                node_count: 0,
            };
            store.addWorkflow(selectedFolderId, workflowApp);
            setSelectedWorkflow(workflowApp);
            setPendingWorkflowSelect(workflowApp.id);
            const newParams = buildWorkflowParams(workflowApp.id);
            newParams.set('new', 'true');
            newParams.delete('action');
            navigate(`?${newParams.toString()}`);
        },
        [store, selectedFolderId, buildWorkflowParams, navigate]
    );

    // Reentrancy guard for createBlankWorkflow. Separate from `isCreatingWorkflow`
    // because that state is pre-set to true at mount in the post-onboarding flow
    // (so the spinner shows without flicker) — using it as the guard would cause
    // the post-onboarding effect to bail before firing the API request.
    const creatingWorkflowRef = useRef(false);

    // Create a blank workflow directly and hand off to FlowCanvas, where the
    // empty-state overlay guides the user into describing what they want to build.
    const createBlankWorkflow = useCallback(async () => {
        if (creatingWorkflowRef.current) return;
        creatingWorkflowRef.current = true;
        setIsCreatingWorkflow(true);
        // Creating makes a workflow the user owns, so if they're filtered to
        // "Not owned by me" switch back to "Owned by anyone" — otherwise the new
        // flow is hidden when they return to the grid.
        if (ownershipFilter === 'not_owned') setOwnershipFilter('all');
        try {
            const visibility = orgContext?.id ? 'organization' : 'personal';
            const response = (await sendEventAsync(
                WorkflowCreateRequest.create({
                    request_id: crypto.randomUUID(),
                    name: 'Untitled',
                    description: '',
                    workflow_data: { nodes: [], edges: [] },
                    permissions: { public: [], shared_with: {} },
                    visibility,
                    organization_permission:
                        visibility === 'organization' ? 'edit' : undefined,
                    folder_id: selectedFolderId,
                }),
                undefined,
                30000
            )) as {
                error?: string;
                workflow?: { id: string; name: string; description?: string };
            };
            if (response.error) throw new Error(response.error);
            if (!response.workflow)
                throw new Error('Failed to create workflow');
            commitNewWorkflow({
                id: response.workflow.id,
                name: response.workflow.name,
                description: response.workflow.description || '',
            });
        } catch (err) {
            console.error('Error creating blank workflow:', err);
            const msg = err instanceof Error ? err.message : '';
            if (isPlanLimitError(msg)) setPlanLimitError(msg);
        } finally {
            // Always reset so a later delete (which clears selectedWorkflow) can't
            // revive the full-screen spinner indefinitely.
            creatingWorkflowRef.current = false;
            setIsCreatingWorkflow(false);
        }
    }, [
        orgContext?.id,
        selectedFolderId,
        commitNewWorkflow,
        ownershipFilter,
        setOwnershipFilter,
    ]);

    const { isConnected } = useSocketConnection('API');

    // Post-onboarding auto-create: wait for socket, consume the latch, fire once.
    // Yields to ANY staged deferred-open intent (invite / scaffold / fork / hero
    // prompt) — a user who arrived through one of those should land on THAT flow,
    // not a fresh blank one. Each intent's consumer below clears the latch.
    useEffect(() => {
        if (!postOnboardingPendingRef.current || !isConnected) return;
        if (hasPendingDeferredOpen()) return;
        postOnboardingPendingRef.current = false;
        clearPostOnboardingFlow();
        createBlankWorkflow();
    }, [isConnected, createBlankWorkflow]);

    // Invite-link landing: /i/<token> stashed the token and routed here. Once the
    // socket is up, redeem it (writes a share row granting this user access) and
    // open the SAME shared workflow — no fork. Takes precedence over the
    // post-onboarding blank-create above.
    const inviteAcceptedRef = useRef(false);
    useEffect(() => {
        if (!isConnected || inviteAcceptedRef.current) return;
        const token = sessionStorage.getItem(PENDING_INVITE_KEY);
        if (!token) return;
        inviteAcceptedRef.current = true;
        // Cancel any post-onboarding blank-create so we don't race it.
        postOnboardingPendingRef.current = false;
        clearPostOnboardingFlow();
        sessionStorage.removeItem(PENDING_INVITE_KEY);

        sendEventAsync(ShareInviteAcceptRequest.create({ token }))
            .then((response: any) => {
                if (response?.error) throw new Error(response.error);
                // The share row now exists — refresh the shared-with-me list so the
                // just-joined flow is in the grid when the user navigates back from
                // FlowCanvas (otherwise it only appears after a manual reload).
                store.refreshSharedWorkflows();
                // Conversion: a recipient joined a flow via an invite link.
                logActivity(EVENTS.INVITE_ACCEPTED, {
                    workflow_id: response?.workflow_id,
                    new_user: !!response?.refresh_jwt,
                });
                // The redeem onboards a first-time joiner server-side; tell the
                // dashboard to refresh the JWT so the onboarding gate clears.
                if (response?.refresh_jwt) {
                    document.dispatchEvent(
                        new CustomEvent('noclick:invite:onboarded')
                    );
                }
                if (response?.workflow_id) {
                    // Open the shared flow via the URL → state path (placeholder +
                    // FlowCanvas fetch); collaboration connects once access is granted.
                    const params = buildWorkflowParams(response.workflow_id);
                    navigate(`?${params.toString()}`, { replace: true });
                }
            })
            .catch((err: unknown) => {
                console.error('Error accepting workflow invite:', err);
                logActivity(EVENTS.INVITE_ACCEPT_FAILED, {
                    error: String(err),
                });
                // Redeem failed — the server didn't create the joiner's onboarding
                // row, so tell the dashboard to un-suppress onboarding (it optimistically
                // skips the questionnaire for invite joiners). Without this the user is
                // locked out of onboarding for the whole session.
                document.dispatchEvent(
                    new CustomEvent('noclick:invite:onboard-failed')
                );
            });
    }, [isConnected, buildWorkflowParams, navigate, logActivity, store]);

    // Switch the browser to a non-grid system view (Trash), clearing
    // folder/workflow selection. Defined above runBrowserAction so the
    // shortcut-driven actions below can call it.
    const selectView = useCallback(
        (mode: Exclude<ViewMode, 'grid'>) => {
            setSelectedFolderIdRaw(null);
            setSelectedWorkflow(null);
            setPendingBackNavigation(true);
            setPendingWorkflowSelect(null);
            setViewMode(mode);
            const newParams = new URLSearchParams(location.search);
            if (newParams.has('workflow')) {
                newParams.delete('workflow');
                setTimeout(() => navigate(`?${newParams.toString()}`), 0);
            }
        },
        [navigate, location.search]
    );

    // Single home for the command-palette browser actions (invoked via
    // runFlowIntent). "new-folder" just opens the dialog; "create" needs the
    // socket, so if it isn't up yet we defer to the ?action= effect (which
    // re-runs on connect) rather than firing a create that would hang.
    // "trash" flips the browser to that system view.
    const runBrowserAction = useCallback(
        (action: BrowserAction) => {
            if (action === 'new-folder') {
                setDialog({ kind: 'createFolder' });
                return;
            }
            if (action === 'trash') {
                selectView('trash');
                return;
            }
            if (isConnected) {
                createBlankWorkflow();
            } else {
                const next = new URLSearchParams(location.search);
                next.set('tab', 'workflows');
                next.set('action', 'create');
                navigate(`?${next.toString()}`, { replace: true });
            }
        },
        [
            isConnected,
            createBlankWorkflow,
            navigate,
            location.search,
            selectView,
        ]
    );

    // External entry points (the global command palette) drive "New workflow" and
    // "New folder" via ?action=create / ?action=new-folder, mirroring the
    // ?action=fork convention. The param is consumed once, then stripped from the
    // URL so it can't re-fire. Workflow creation waits for the socket connection;
    // the effect re-runs when isConnected flips.
    const browserActionHandledRef = useRef(false);
    useEffect(() => {
        const action = new URLSearchParams(location.search).get('action');
        if (action !== 'create' && action !== 'new-folder') {
            browserActionHandledRef.current = false;
            return;
        }
        if (browserActionHandledRef.current) return;
        if (action === 'create' && !isConnected) return;

        browserActionHandledRef.current = true;
        if (action === 'create') createBlankWorkflow();
        else setDialog({ kind: 'createFolder' });

        const next = new URLSearchParams(location.search);
        next.delete('action');
        navigate(`?${next.toString()}`, { replace: true });
    }, [location.search, isConnected, createBlankWorkflow, navigate]);

    // Hero-prompt hand-off: the public landing's HeroPromptShowcase stashes
    // {prompt, tab, ts} in sessionStorage under `noclick:hero-prompt`, then
    // funnels into signup or `/dashboard`. Once we're connected, pop the
    // entry, move it to `:pending` (so a reload can't re-trigger creation),
    // and create a blank workflow. FlowCanvasEmptyState consumes `:pending`
    // and dispatches the prompt to the agent.
    const heroPromptFiredRef = useRef(false);
    useEffect(() => {
        if (heroPromptFiredRef.current || !isConnected) return;
        const raw =
            typeof window !== 'undefined'
                ? sessionStorage.getItem(HERO_PROMPT_KEY)
                : null;
        if (!raw) return;
        let parsed: {
            prompt?: string;
            tab?: 'canvas' | 'interface';
            ts?: number;
        } | null = null;
        try {
            parsed = JSON.parse(raw);
        } catch {
            sessionStorage.removeItem(HERO_PROMPT_KEY);
            return;
        }
        // Ignore stale entries (>15min old) so an abandoned tab doesn't auto-create
        // a workflow next session.
        if (
            !parsed?.prompt ||
            (parsed.ts && Date.now() - parsed.ts > 15 * 60 * 1000)
        ) {
            sessionStorage.removeItem(HERO_PROMPT_KEY);
            return;
        }
        heroPromptFiredRef.current = true;
        // This IS the blank-create; cancel the post-onboarding one so they don't race.
        postOnboardingPendingRef.current = false;
        clearPostOnboardingFlow();
        sessionStorage.removeItem(HERO_PROMPT_KEY);
        sessionStorage.setItem(
            'noclick:hero-prompt:pending',
            JSON.stringify(parsed)
        );
        createBlankWorkflow();
    }, [isConnected, createBlankWorkflow]);

    // Fork flow: PublicWorkflowView stashes the source workflow in sessionStorage and
    // navigates here. Pick it up once the socket is connected, perform the fork, and
    // land the user on FlowCanvas with the setup tab open.
    const forkExecutedRef = useRef(false);
    useEffect(() => {
        if (!isConnected || forkExecutedRef.current) return;
        const forkDataStr = sessionStorage.getItem(FORK_DATA_KEY);
        if (!forkDataStr) return;
        forkExecutedRef.current = true;
        // Opening the fork supersedes the post-onboarding blank-create.
        postOnboardingPendingRef.current = false;
        clearPostOnboardingFlow();
        sessionStorage.removeItem(FORK_DATA_KEY);
        let forkData: { sourceId: string; name?: string };
        try {
            forkData = JSON.parse(forkDataStr);
        } catch {
            return;
        }
        if (!forkData.sourceId) return;

        setIsCreatingWorkflow(true);
        const dest = orgContext?.id ? 'organization' : 'personal';
        sendEventAsync(
            ResourceForkRequest.create({
                request_id: crypto.randomUUID(),
                resource_type: 'workflow',
                resource_id: forkData.sourceId,
                destination_type: dest,
                destination_org_id:
                    dest === 'organization' ? orgContext!.id! : undefined,
                new_name: forkData.name || 'Untitled',
                include_data: false,
            }),
            undefined,
            60000
        )
            .then((response: any) => {
                if (response.error) throw new Error(response.error);
                if (response.success && response.forked_resource) {
                    sessionStorage.setItem('noclick_open_setup_tab', 'true');
                    // Template forks get the onboarding FULL SCREEN — the
                    // published-agent experience, not a tab inside the canvas.
                    sessionStorage.setItem('noclick_setup_fullscreen', 'true');
                    // Combo-page forks name the harness up front; Setup's
                    // agent step consumes this and preselects it.
                    const pendingHarness = sessionStorage.getItem('noclick_pending_fork_harness');
                    if (pendingHarness) {
                        sessionStorage.removeItem('noclick_pending_fork_harness');
                        sessionStorage.setItem(
                            `noclick_setup_harness_model:${response.forked_resource.id}`,
                            pendingHarness
                        );
                    }
                    commitNewWorkflow({
                        id: response.forked_resource.id,
                        name: response.forked_resource.name,
                        description: '',
                    });
                } else {
                    throw new Error(
                        response.message || 'Failed to create from template'
                    );
                }
            })
            .catch((err: unknown) => {
                console.error('Error forking workflow:', err);
                const msg = err instanceof Error ? err.message : '';
                if (isPlanLimitError(msg)) setPlanLimitError(msg);
            })
            .finally(() => {
                // Always reset so a later delete can't resurrect the full-screen spinner.
                setIsCreatingWorkflow(false);
            });
    }, [isConnected, orgContext?.id, commitNewWorkflow]);

    // Scaffold flow: the /agents marketing pages stash a {name, workflowData} blob
    // (a harness agent pre-wired with tool providers) and route here. Once the
    // socket is up, create a NEW workflow from that blob and open it on the canvas
    // with the setup tab open so the user connects the providers' credentials.
    // Mirrors the fork consumer above, but uses WorkflowCreateRequest (there is no
    // source workflow to fork — the graph is built client-side on the page).
    const scaffoldExecutedRef = useRef(false);
    useEffect(() => {
        if (!isConnected || scaffoldExecutedRef.current) return;
        const raw = sessionStorage.getItem(SCAFFOLD_DATA_KEY);
        if (!raw) return;
        scaffoldExecutedRef.current = true;
        // Opening the scaffold supersedes the post-onboarding blank-create — this is
        // the fix for scaffolds being dropped when a new user passes through onboarding.
        postOnboardingPendingRef.current = false;
        clearPostOnboardingFlow();
        sessionStorage.removeItem(SCAFFOLD_DATA_KEY);
        sessionStorage.removeItem(PENDING_SCAFFOLD_KEY);
        let intent: {
            name?: string;
            workflowData?: { nodes: unknown[]; edges: unknown[] };
            builderPrompt?: string;
            setup?: { runtime?: string };
        };
        try {
            intent = JSON.parse(raw);
        } catch {
            return;
        }
        if (!intent.workflowData?.nodes?.length) return;

        // Persist the onboarding skip server-side. Arriving via a scaffold defers
        // onboarding, but the suppression above is session-only (a sessionStorage
        // flag consumed on this very mount) — without a durable `user_onboarding_responses`
        // row the `onboarding_completed` JWT claim stays false and the questionnaire
        // re-appears on the next dashboard remount (e.g. after creating a workflow).
        // Mirrors the invite-join path; the dashboard refreshes the JWT on success.
        sendEventAsync<{ refresh_jwt?: boolean }>(
            OnboardingSkipRequest.create({ source: 'scaffold' })
        )
            .then((res) => {
                if (res?.refresh_jwt) {
                    document.dispatchEvent(
                        new CustomEvent('noclick:onboarding:persisted')
                    );
                }
            })
            .catch((err: unknown) =>
                console.error(
                    'Failed to persist scaffold onboarding skip:',
                    err
                )
            );

        if (ownershipFilter === 'not_owned') setOwnershipFilter('all');
        setIsCreatingWorkflow(true);
        const visibility = orgContext?.id ? 'organization' : 'personal';
        sendEventAsync(
            WorkflowCreateRequest.create({
                request_id: crypto.randomUUID(),
                name: intent.name || 'Untitled',
                description: '',
                workflow_data: intent.workflowData,
                permissions: { public: [], shared_with: {} },
                visibility,
                organization_permission:
                    visibility === 'organization' ? 'edit' : undefined,
                folder_id: selectedFolderId,
            }),
            undefined,
            30000
        )
            .then(
                (response) => {
                    if (response.error) throw new Error(response.error);
                    if (!response.workflow)
                        throw new Error('Failed to create agent');
                    sessionStorage.setItem('noclick_open_setup_tab', 'true');
                    if (intent.setup) {
                        // Wizard scaffold: choices (runtime, presets) are already
                        // baked into the graph, so setup is the deterministic
                        // full-screen takeover and the AI builder stays out of it.
                        sessionStorage.setItem('noclick_setup_fullscreen', 'true');
                    } else if (intent.builderPrompt) {
                        // Bare scaffold: hand the guiding prompt to the canvas, which
                        // auto-sends it to the AI builder once the workflow's nodes
                        // hydrate (see FlowCanvas). Keyed by workflow id so a crash/
                        // reload can never deliver it into a different workflow.
                        sessionStorage.setItem(
                            `noclick_scaffold_builder_prompt:${response.workflow.id}`,
                            intent.builderPrompt
                        );
                    }
                    commitNewWorkflow({
                        id: response.workflow.id,
                        name: response.workflow.name,
                        description: response.workflow.description || '',
                    });
                }
            )
            .catch((err: unknown) => {
                console.error('Error creating agent scaffold:', err);
                const msg = err instanceof Error ? err.message : '';
                if (isPlanLimitError(msg)) setPlanLimitError(msg);
            })
            .finally(() => {
                setIsCreatingWorkflow(false);
            });
    }, [
        isConnected,
        orgContext?.id,
        selectedFolderId,
        commitNewWorkflow,
        ownershipFilter,
        setOwnershipFilter,
    ]);

    // Folder card/sidebar emit a folder *id*; look up current folder to build the dialog payload.
    const handleShareFolder = useCallback(
        (folderId: string) => {
            const folder = currentFolders.find((f) => f.id === folderId);
            setDialog({
                kind: 'shareFolder',
                id: folderId,
                name: folder?.name ?? 'Folder',
            });
        },
        [currentFolders]
    );

    const handleSettingsFolder = useCallback(
        (folderId: string) => {
            const folder = currentFolders.find((f) => f.id === folderId);
            if (folder) setDialog({ kind: 'editFolder', folder });
        },
        [currentFolders]
    );

    // Adapter: the sidebar tree emits a trimmed shape; we synthesize a WorkflowApp.
    // Ownership defaults to edit because items visible in the tree are the user's own.
    const handleWorkflowClickFromTree = useCallback(
        (workflow: { id: string; name: string; description?: string }) => {
            handleWorkflowSelect({
                id: workflow.id,
                name: workflow.name,
                description: workflow.description || '',
                is_owner: true,
                user_permission: 'edit',
            });
        },
        [handleWorkflowSelect]
    );

    // Run a flow intent from the command palette: open a workflow via the same
    // synchronous path a card/tree click uses (setSelectedWorkflow immediately →
    // FlowCanvas mounts from cache), or run a browser action. The palette
    // previously navigate()'d and relied on the URL→useEffect round-trip, which
    // felt slow even when the flow's data was already cached.
    const runFlowIntent = useCallback(
        (intent: FlowIntent) => {
            if (intent.kind === 'open') {
                if (intent.workflow?.id)
                    handleWorkflowClickFromTree(intent.workflow);
            } else {
                runBrowserAction(intent.action);
            }
        },
        [handleWorkflowClickFromTree, runBrowserAction]
    );

    // Same-tab fast path: the browser is already mounted on the flow tab, so the
    // noclick:flow-intent event fires here. Clear the latch so the mount effect
    // can't also fire on a later remount.
    useEffect(() => {
        const handleIntent = (e: Event) => {
            consumePendingFlowIntent();
            runFlowIntent((e as CustomEvent<FlowIntent>).detail);
        };
        window.addEventListener('noclick:flow-intent', handleIntent);
        return () =>
            window.removeEventListener('noclick:flow-intent', handleIntent);
    }, [runFlowIntent]);

    // Cross-tab fast path: navigateToWorkflow / triggerBrowserAction switched to
    // the flow tab from another screen (e.g. usage dashboard), so this browser
    // mounts fresh and the event already fired with no listener. Consume the latch
    // here in a layout effect (before paint) so the flow / action happens in the
    // first frame — no browser-grid flash, no URL→useEffect round-trip.
    const pendingConsumedRef = useRef(false);
    useLayoutEffect(() => {
        if (pendingConsumedRef.current) return;
        pendingConsumedRef.current = true;
        const intent = consumePendingFlowIntent();
        if (intent) runFlowIntent(intent);
    }, [runFlowIntent]);

    const handleForkSuccess = useCallback(() => {
        // Refresh the workflow list to show the newly forked workflow
        store.fetchWorkflows(selectedFolderId);
    }, [store, selectedFolderId]);

    const handleFolderCreated = useCallback(() => {
        // Refresh the full tree so both grid and sidebar stay in sync
        store.refreshTree();
    }, [store]);

    const handleDeleteFolder = useCallback(
        (folderId: string) => {
            const folder = currentFolders.find((f) => f.id === folderId);
            setDialog({
                kind: 'deleteFolder',
                id: folderId,
                name: folder?.name ?? 'Folder',
            });
        },
        [currentFolders]
    );

    // Ownership of the thing being deleted, keyed on the authoritative is_owner
    // flag (workflow:list / get_tree always set it) rather than shared-list
    // membership — so the leave-vs-delete decision is right even before the
    // shared list has loaded.
    const isWorkflowNotOwned = useCallback(
        (workflowId: string): boolean => {
            for (const list of Object.values(store.workflowsByFolder)) {
                const w = list?.find((x) => x.id === workflowId);
                if (w) return w.is_owner === false;
            }
            if (store.sharedWorkflows.some((w) => w.id === workflowId))
                return true;
            if (selectedWorkflow?.id === workflowId)
                return selectedWorkflow.is_owner === false;
            return false;
        },
        [store, selectedWorkflow]
    );

    const isFolderNotOwned = useCallback(
        (folderId: string): boolean => {
            const f = store.getAllFolders().find((x) => x.id === folderId);
            if (f) return f.is_owner === false;
            return store.sharedFolders.some((x) => x.id === folderId);
        },
        [store]
    );

    // Drop the caller's own access to a shared resource (workflow/folder) instead
    // of deleting it. share:leave is idempotent; removed===false means access came
    // via an org share (not droppable individually), so we restore + explain.
    const leaveSharedResource = useCallback(
        (
            resourceType: 'workflow' | 'workflow_folder',
            resourceId: string,
            optimisticRemove: () => void,
            rollback: () => void
        ) => {
            optimisticRemove();
            sendEventWithCallback(
                ShareLeaveRequest.create({
                    resource_type: resourceType,
                    resource_id: resourceId,
                }),
                (response) => {
                    if (response.error) {
                        console.error(
                            'Failed to leave shared resource:',
                            response.error
                        );
                        alert(`Failed to remove: ${response.error}`);
                        rollback();
                    } else if (!response.removed) {
                        rollback();
                        alert(
                            "This is shared with your whole organization, so it can't be removed individually."
                        );
                    }
                }
            );
        },
        []
    );

    const handleDeleteFolderConfirm = useCallback(
        (folderId?: string) => {
            if (!folderId) return;

            // Capture the scope for rollback before any optimistic mutation.
            const rollback = store.captureRollback();

            // If we're currently inside the folder being deleted, navigate to parent
            if (selectedFolderId === folderId) {
                setSelectedFolderId(null);
            }

            // Shared (not-owned) folders aren't ours to delete — leave instead, same
            // as shared workflows (workflow_folder:delete would fail "only the owner").
            if (isFolderNotOwned(folderId)) {
                closeDialog();
                leaveSharedResource(
                    'workflow_folder',
                    folderId,
                    () => {
                        store.removeFolder(folderId);
                        store.removeSharedFolder(folderId);
                    },
                    rollback
                );
                return;
            }

            // Optimistic: remove folder from tree
            store.removeFolder(folderId);
            closeDialog();

            sendEventWithCallback(
                FolderDeleteRequest.create({
                    folder_id: folderId,
                }),
                (response) => {
                    if (!response.success) {
                        console.error(
                            'Failed to delete folder:',
                            response.message
                        );
                        alert(`Failed to delete folder: ${response.message}`);
                        rollback();
                    } else {
                        // Refresh tree + workflows (deleted folder's workflows moved to parent)
                        store.refreshTree();
                        store.fetchWorkflows(selectedFolderId);
                    }
                }
            );
        },
        [
            store,
            selectedFolderId,
            setSelectedFolderId,
            closeDialog,
            isFolderNotOwned,
            leaveSharedResource,
        ]
    );

    const handleCreateFolder = useCallback(
        (data: { name: string; description: string }) => {
            if (!data.name.trim()) return;

            setCreatingFolder(true);
            sendEventWithCallback(
                {
                    event_name: 'workflow_folder:create' as const,
                    name: data.name.trim(),
                    description: data.description.trim(),
                    parent_folder_id: selectedFolderId,
                },
                (response: FolderCreateResponse) => {
                    setCreatingFolder(false);
                    if (response.success && response.folder) {
                        closeDialog();
                        store.refreshTree();
                    } else {
                        console.error(
                            'Failed to create folder:',
                            response.message
                        );
                        alert(
                            `Failed to create folder: ${response.message || 'Unknown error'}`
                        );
                    }
                }
            );
        },
        [selectedFolderId, store, closeDialog]
    );

    const handleUpdateWorkflow = useCallback(
        (
            workflowId: string,
            updates: { name?: string; description?: string }
        ) => {
            sendEventWithCallback(
                WorkflowUpdateRequest.create({
                    workflow_id: workflowId,
                    name: updates.name,
                    description: updates.description,
                }),
                (response) => {
                    if (response.error) {
                        console.error(
                            'Failed to update workflow:',
                            response.error
                        );
                        alert(`Failed to update workflow: ${response.error}`);
                    } else if (response.workflow) {
                        store.updateWorkflow(workflowId, {
                            name: response.workflow.name,
                            description: response.workflow.description,
                        });
                        closeDialog();
                    }
                }
            );
        },
        [store, closeDialog]
    );

    const handleUpdateFolder = useCallback(
        (
            folderId: string,
            updates: { name?: string; description?: string }
        ) => {
            sendEventWithCallback(
                FolderUpdateRequest.create({
                    folder_id: folderId,
                    name: updates.name,
                    description: updates.description,
                }),
                (response) => {
                    if (!response.success) {
                        console.error(
                            'Failed to update folder:',
                            response.message
                        );
                        alert(`Failed to update folder: ${response.message}`);
                    } else if (response.folder) {
                        store.updateFolder(folderId, {
                            name: response.folder.name,
                            description: response.folder.description ?? '',
                        });
                        closeDialog();
                    }
                }
            );
        },
        [store, closeDialog]
    );

    // Edit popup → delete confirm. Setting a new dialog kind implicitly closes the edit dialog.
    const handleDeleteFromEdit = useCallback((workflowId: string) => {
        setDialog({ kind: 'deleteWorkflow', workflowId });
    }, []);

    const handleDeleteFolderFromEdit = useCallback(
        (folderId: string) => {
            const folder = currentFolders.find((f) => f.id === folderId);
            setDialog({
                kind: 'deleteFolder',
                id: folderId,
                name: folder?.name ?? 'Folder',
            });
        },
        [currentFolders]
    );

    const handleDeleteConfirm = useCallback(
        (workflowId: string) => {
            // If deleting the currently open workflow, navigate back first
            if (selectedWorkflow?.id === workflowId) {
                flowCanvasKeyRef.current = null;
                handleBackFromFlowCanvas();
            }

            // Not-owned flows aren't ours to delete — "deleting" them drops our own
            // access (share:leave) so they stop showing on our end; workflow:delete
            // would fail with "workflow not found". The same flow can sit in BOTH the
            // workflow:list copy and the shared list, so clear both.
            // Capture the scope for rollback before any optimistic mutation.
            const rollback = store.captureRollback();

            if (isWorkflowNotOwned(workflowId)) {
                closeDialog();
                leaveSharedResource(
                    'workflow',
                    workflowId,
                    () => {
                        store.removeWorkflowGlobal(workflowId);
                        store.removeSharedWorkflow(workflowId);
                    },
                    () => {
                        store.clearRemovalTombstone(workflowId);
                        rollback();
                    }
                );
                return;
            }

            // Optimistic: remove from unified store (updates grid + sidebar)
            store.removeWorkflow(workflowId, selectedFolderId);
            closeDialog();

            sendEventWithCallback(
                WorkflowDeleteRequest.create({
                    workflow_id: workflowId,
                }),
                (response) => {
                    if (response.error) {
                        console.error(
                            'Failed to delete workflow:',
                            response.error
                        );
                        alert(`Failed to delete workflow: ${response.error}`);
                        store.clearRemovalTombstone(workflowId);
                        rollback();
                    }
                }
            );
        },
        [
            store,
            selectedFolderId,
            selectedWorkflow,
            handleBackFromFlowCanvas,
            closeDialog,
            isWorkflowNotOwned,
            leaveSharedResource,
        ]
    );

    // Switch to a non-grid view (trash or shared): clear any open workflow/folder selection.
    // Also strip the workflow query param from the URL — without this, the URL→state
    // sync effect re-selects the workflow on the next render, defeating the close.
    // Fetch workflows when folder changes or org switches (SWR: cached data shown instantly, fresh fetch in background)
    useEffect(() => {
        store.fetchWorkflows(selectedFolderId);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [selectedFolderId, scopeId]);

    // Callback to navigate to a different workflow (used by MCP open_workflow)
    const handleNavigateToWorkflow = useCallback(
        (workflowId: string) => {
            const workflow = workflows.find((w) => w.id === workflowId);
            // If not in the cached list yet, mount a placeholder so FlowCanvas can fetch
            setSelectedWorkflow(
                workflow ?? {
                    id: workflowId,
                    name: 'Loading...',
                    description: '',
                }
            );
        },
        [workflows]
    );

    // While we're creating/forking a workflow before FlowCanvas mounts, show a
    // full-screen loader to avoid a flash of the browser grid.
    if (isCreatingWorkflow && !selectedWorkflow) {
        return (
            <div className="h-full w-full flex items-center justify-center bg-background">
                <Loader2 className="w-6 h-6 text-muted-foreground/70 dark:text-white/40 animate-spin" />
            </div>
        );
    }

    // Update FlowCanvas key when workflow changes
    // This ensures FlowCanvas remounts when switching between different workflows
    if (selectedWorkflow) {
        // Update key if it's different from current workflow
        if (flowCanvasKeyRef.current !== selectedWorkflow.id) {
            flowCanvasKeyRef.current = selectedWorkflow.id;
        }
    } else {
        // Clear the stable key when no workflow is selected
        flowCanvasKeyRef.current = null;
    }

    // Props common to desktop and mobile sidebar renders. The mobile overlay
    // additionally closes itself after navigation/selection actions.
    const sidebarCommonProps = {
        treeData: store.folderTree,
        loadingTree: store.loadingTree,
        onExpandFolder: (folderId: string | null) =>
            store.fetchWorkflows(folderId),
        selectedFolderId,
        selectedWorkflowId: selectedWorkflow?.id || null,
        onFolderShare: handleShareFolder,
        onDeleteFolder: handleDeleteFolder,
        onFolderCreated: handleFolderCreated,
        onSidebarSelection: (fns: {
            getSelectedIds: () => string[];
            clearSelection: () => void;
        }) => {
            drag.sidebarSelectionRef.current = fns;
        },
        isTrashView: viewMode === 'trash',
    };

    // The delete-confirm dialogs double as "remove a shared item": for a not-owned
    // workflow/folder the action unshares (share:leave) instead of deleting, so the
    // copy reflects that. Keyed on the same is_owner lookup the handlers use.
    const deletingSharedFlow =
        dialog.kind === 'deleteWorkflow' &&
        isWorkflowNotOwned(dialog.workflowId);
    const deletingSharedFolder =
        dialog.kind === 'deleteFolder' && isFolderNotOwned(dialog.id);

    // Otherwise, show the browsable card view with folder navigation
    return (
        <>
            <DndContext
                sensors={drag.sensors}
                collisionDetection={pointerWithin}
                onDragStart={drag.handleDragStart}
                onDragEnd={drag.handleDragEnd}
            >
                <div className="h-full flex relative">
                    {/* Desktop: inline sidebar */}
                    {!isMobile && (
                        <FolderTreeSidebarArborist
                            {...sidebarCommonProps}
                            onFolderSelect={(folderId) => {
                                if (folderId === null && selectedWorkflow) {
                                    handleBackFromFlowCanvas();
                                }
                                setSelectedFolderId(folderId);
                            }}
                            onWorkflowClick={handleWorkflowClickFromTree}
                            isCollapsed={sidebarCollapsed}
                            onToggleCollapse={() =>
                                setSidebarCollapsed(!sidebarCollapsed)
                            }
                            onTrashSelect={() => selectView('trash')}
                            className={cn(
                                'flex-shrink-0 relative',
                                // When a workflow (FlowCanvas) is open, raise the
                                // sidebar over the canvas with a soft right-edge
                                // shadow, mirroring the canvas navbar's elevation.
                                selectedWorkflow &&
                                    'z-10 shadow-[5px_0_16px_-7px_rgba(0,0,0,0.11)] dark:shadow-[5px_0_16px_-7px_rgba(0,0,0,0.35)]'
                            )}
                        />
                    )}

                    {/* Mobile: full-screen overlay sidebar — each action also closes the overlay */}
                    {isMobile && mobileSidebarOpen && (
                        <>
                            <div
                                className="absolute inset-0 z-20 bg-black/50"
                                onClick={() => setMobileSidebarOpen(false)}
                            />
                            <div className="absolute inset-0 z-30 flex flex-col">
                                <FolderTreeSidebarArborist
                                    {...sidebarCommonProps}
                                    onFolderSelect={(folderId) => {
                                        if (
                                            folderId === null &&
                                            selectedWorkflow
                                        ) {
                                            handleBackFromFlowCanvas();
                                        }
                                        setSelectedFolderId(folderId);
                                        setMobileSidebarOpen(false);
                                    }}
                                    onWorkflowClick={(workflow) => {
                                        handleWorkflowClickFromTree(workflow);
                                        setMobileSidebarOpen(false);
                                    }}
                                    isCollapsed={false}
                                    onToggleCollapse={() =>
                                        setMobileSidebarOpen(false)
                                    }
                                    onTrashSelect={() => {
                                        selectView('trash');
                                        setMobileSidebarOpen(false);
                                    }}
                                    className="flex-1 w-full"
                                />
                            </div>
                        </>
                    )}

                    {/* Main Content Area */}
                    <div className="flex-1 h-full overflow-y-auto scrollbar-subtle">
                        {selectedWorkflow ? (
                            /* Show FlowCanvas when a workflow is selected (lazy-loaded) */
                            <Suspense
                                fallback={
                                    <div className="flex-1 h-full w-full bg-background dark:bg-zinc-950" />
                                }
                            >
                                <FlowCanvas
                                    key={
                                        flowCanvasKeyRef.current ||
                                        selectedWorkflow.id
                                    }
                                    workflowTitle={selectedWorkflow.name}
                                    workflowId={selectedWorkflow.id}
                                    onBack={() => {
                                        flowCanvasKeyRef.current = null; // Clear key when leaving
                                        handleBackFromFlowCanvas();
                                    }}
                                    onDelete={(wfId) =>
                                        setDialog({
                                            kind: 'deleteWorkflow',
                                            workflowId: wfId,
                                        })
                                    }
                                    onTitleChange={(newTitle) => {
                                        handleUpdateWorkflow(
                                            selectedWorkflow.id,
                                            { name: newTitle }
                                        );
                                        // Also update the selected workflow state for immediate UI feedback
                                        setSelectedWorkflow({
                                            ...selectedWorkflow,
                                            name: newTitle,
                                        });
                                    }}
                                    onNavigateToWorkflow={
                                        handleNavigateToWorkflow
                                    }
                                />
                            </Suspense>
                        ) : viewMode === 'trash' ? (
                            <TrashView
                                isMobile={isMobile}
                                onOpenMobileSidebar={() =>
                                    setMobileSidebarOpen(true)
                                }
                            />
                        ) : (
                            /* Show folder/workflow browser when no workflow is selected */
                            <div
                                className={cn(
                                    'p-4 pt-1 min-h-full',
                                    isMobile ? 'px-2 space-y-2' : 'space-y-1'
                                )}
                                onClick={(e) => {
                                    // Clear multi-selection when clicking empty space (not on a card, folder, or button)
                                    if (
                                        !(e.target as HTMLElement).closest(
                                            '[data-workflow-card], [data-folder-card], button, a'
                                        )
                                    ) {
                                        selection.clearSelection();
                                    }
                                }}
                            >
                                {/* Folder Header with Breadcrumbs */}
                                {selectedFolderId ? (
                                    <DroppableHeaderBar
                                        folderId={null}
                                        idSuffix="header-root"
                                        className={
                                            isMobile
                                                ? 'pl-0 flex-wrap gap-y-2'
                                                : undefined
                                        }
                                    >
                                        {isMobile && (
                                            <Button
                                                size="sm"
                                                variant="ghost"
                                                className="h-10 w-10 p-0 hover:bg-accent flex-shrink-0"
                                                onClick={() =>
                                                    setMobileSidebarOpen(true)
                                                }
                                                title="Browse folders"
                                            >
                                                <PanelLeft className="w-5 h-5 text-muted-foreground" />
                                            </Button>
                                        )}
                                        <FolderBreadcrumbs
                                            folderId={selectedFolderId}
                                            folderPath={
                                                selectedFolderId
                                                    ? store.getFolderPath(
                                                          selectedFolderId
                                                      )
                                                    : []
                                            }
                                            onNavigate={setSelectedFolderId}
                                            className="flex-1 min-w-0"
                                        />
                                        <div
                                            className={cn(
                                                'flex items-center gap-2',
                                                isMobile
                                                    ? 'flex-wrap'
                                                    : 'flex-shrink-0'
                                            )}
                                        >
                                            <OwnershipFilterDropdown
                                                value={ownershipFilter}
                                                onChange={setOwnershipFilter}
                                            />
                                            <LayoutToggle
                                                mode={layoutMode}
                                                onChange={setLayoutMode}
                                            />
                                            <ShortcutTooltip keys={['N', 'F']}>
                                                <button
                                                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-card dark:bg-secondary/60 border border-border dark:border-zinc-700/50 hover:border-muted-foreground/40 dark:hover:border-zinc-600/50 hover:bg-muted dark:hover:bg-secondary transition-colors flex-shrink-0"
                                                    onClick={() =>
                                                        setDialog({
                                                            kind: 'createFolder',
                                                        })
                                                    }
                                                >
                                                    <FolderPlus className="w-3.5 h-3.5 text-muted-foreground" />
                                                    <span className="text-xs text-muted-foreground">
                                                        New Folder
                                                    </span>
                                                </button>
                                            </ShortcutTooltip>
                                            <NewWorkflowButton
                                                onClick={createBlankWorkflow}
                                                isCreating={isCreatingWorkflow}
                                            />
                                        </div>
                                    </DroppableHeaderBar>
                                ) : (
                                    <>
                                        <DroppableHeaderBar
                                            folderId={null}
                                            idSuffix="header-root"
                                            className={
                                                isMobile
                                                    ? 'pl-0 flex-wrap gap-y-2'
                                                    : undefined
                                            }
                                        >
                                            <div
                                                className={cn(
                                                    'flex items-center gap-2',
                                                    !isMobile && 'ml-1'
                                                )}
                                            >
                                                {isMobile && (
                                                    <Button
                                                        size="sm"
                                                        variant="ghost"
                                                        className="h-10 w-10 p-0 hover:bg-accent flex-shrink-0"
                                                        onClick={() =>
                                                            setMobileSidebarOpen(
                                                                true
                                                            )
                                                        }
                                                        title="Browse folders"
                                                    >
                                                        <PanelLeft className="w-5 h-5 text-muted-foreground" />
                                                    </Button>
                                                )}
                                                <Home className="w-4 h-4 text-muted-foreground" />
                                                <span className="text-sm font-medium text-foreground/80">
                                                    All Workflows
                                                </span>
                                            </div>
                                            <div
                                                className={cn(
                                                    'flex items-center gap-2',
                                                    isMobile
                                                        ? 'flex-wrap'
                                                        : 'flex-shrink-0'
                                                )}
                                            >
                                                <OwnershipFilterDropdown
                                                    value={ownershipFilter}
                                                    onChange={
                                                        setOwnershipFilter
                                                    }
                                                />
                                                <LayoutToggle
                                                    mode={layoutMode}
                                                    onChange={setLayoutMode}
                                                />
                                                <ShortcutTooltip
                                                    keys={['N', 'F']}
                                                >
                                                    <button
                                                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-card dark:bg-secondary/60 border border-border dark:border-zinc-700/50 hover:border-muted-foreground/40 dark:hover:border-zinc-600/50 hover:bg-muted dark:hover:bg-secondary transition-colors flex-shrink-0"
                                                        onClick={() =>
                                                            setDialog({
                                                                kind: 'createFolder',
                                                            })
                                                        }
                                                    >
                                                        <FolderPlus className="w-3.5 h-3.5 text-muted-foreground" />
                                                        <span className="text-xs text-muted-foreground">
                                                            New Folder
                                                        </span>
                                                    </button>
                                                </ShortcutTooltip>
                                                <NewWorkflowButton
                                                    onClick={
                                                        createBlankWorkflow
                                                    }
                                                    isCreating={
                                                        isCreatingWorkflow
                                                    }
                                                />
                                            </div>
                                        </DroppableHeaderBar>
                                        {!isMobile && (
                                            <div className="flex flex-wrap gap-2 pb-1">
                                                {CONNECT_INTEGRATIONS.map(
                                                    ({
                                                        type,
                                                        title,
                                                        url,
                                                        Icon,
                                                        iconClassName,
                                                    }) => (
                                                        <a
                                                            key={type}
                                                            onClick={() =>
                                                                setConnectVideo(
                                                                    {
                                                                        title,
                                                                        url,
                                                                        type,
                                                                    }
                                                                )
                                                            }
                                                            className="inline-flex items-center gap-2 px-3 py-1.5 text-xs font-medium bg-card dark:bg-foreground/[0.05] border border-border/60 dark:border-white/[0.08] hover:bg-muted dark:hover:bg-foreground/[0.08] hover:border-border dark:hover:border-white/[0.12] text-foreground/80 rounded-lg transition-colors cursor-pointer"
                                                        >
                                                            <Icon
                                                                className={
                                                                    iconClassName
                                                                }
                                                            />
                                                            {title}
                                                            <ExternalLink className="w-3 h-3 text-muted-foreground dark:text-zinc-500" />
                                                        </a>
                                                    )
                                                )}
                                            </div>
                                        )}
                                    </>
                                )}

                                {/* Create Folder Popup */}
                                <CreateFolderPopup
                                    isOpen={dialog.kind === 'createFolder'}
                                    onOpenChange={(open) =>
                                        !open && closeDialog()
                                    }
                                    onCreateFolder={handleCreateFolder}
                                    isCreating={creatingFolder}
                                    parentFolderName={
                                        selectedFolderId ? 'this folder' : null
                                    }
                                />

                                {layoutMode === 'list' ? (
                                    /* Workflows List — compact rows (same handlers/dnd as the grid).
                       Distinct key vs the grid branch below: both branch roots are
                       <div>, so without it React reconciles one into the other on a
                       layout toggle and reuses stale DOM (cards bleed into list view
                       and vice-versa). The key forces a clean unmount/remount. */
                                    <div
                                        key="workflow-list"
                                        className="space-y-2"
                                        ref={listContainerRef}
                                    >
                                        {/* Search — global (folders + workflows across the tree) */}
                                        <div className="relative">
                                            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground/60 dark:text-white/30 pointer-events-none" />
                                            <input
                                                ref={searchInputRef}
                                                type="text"
                                                value={listSearch}
                                                onChange={(e) =>
                                                    setListSearch(
                                                        e.target.value
                                                    )
                                                }
                                                onKeyDown={handleSearchKeyDown}
                                                placeholder="Search workflows and folders..."
                                                className="w-full pl-9 pr-3 py-2 text-sm bg-foreground/[0.04] border border-border/60 dark:border-white/[0.08] rounded-lg text-foreground placeholder:text-[hsl(var(--placeholder))] outline-none focus:border-border dark:focus:border-white/[0.15] transition-colors"
                                            />
                                        </div>

                                        {/* Merged folder + workflow rows, sorted by last edited */}
                                        {listItems.map((item, i) =>
                                            item.kind === 'folder' ? (
                                                <FolderRow
                                                    key={item.id}
                                                    folder={item.folder}
                                                    isMultiSelected={selection.isSelected(
                                                        item.id
                                                    )}
                                                    isBeingDragged={drag.draggingIds.has(
                                                        item.id
                                                    )}
                                                    onClick={(e) => {
                                                        const action =
                                                            selection.handleClick(
                                                                item.id,
                                                                e
                                                            );
                                                        if (action === 'open')
                                                            setSelectedFolderId(
                                                                item.id
                                                            );
                                                    }}
                                                    onSettings={() =>
                                                        setDialog({
                                                            kind: 'editFolder',
                                                            folder: item.folder,
                                                        })
                                                    }
                                                    onShare={() =>
                                                        setDialog({
                                                            kind: 'shareFolder',
                                                            id: item.id,
                                                            name: item.folder
                                                                .name,
                                                        })
                                                    }
                                                    sourceFolderId={
                                                        selectedFolderId
                                                    }
                                                    isMobile={isMobile}
                                                    dragDisabled={isSearching}
                                                    location={item.location}
                                                    isHighlighted={
                                                        isSearching &&
                                                        i === highlightedIndex
                                                    }
                                                />
                                            ) : (
                                                <WorkflowRow
                                                    key={item.id}
                                                    workflow={item.workflow}
                                                    isMultiSelected={selection.isSelected(
                                                        item.id
                                                    )}
                                                    isBeingDragged={drag.draggingIds.has(
                                                        item.id
                                                    )}
                                                    onClick={(e) => {
                                                        const action =
                                                            selection.handleClick(
                                                                item.id,
                                                                e
                                                            );
                                                        if (action === 'open')
                                                            handleWorkflowSelect(
                                                                item.workflow
                                                            );
                                                    }}
                                                    onSettings={(workflow) =>
                                                        setDialog({
                                                            kind: 'editWorkflow',
                                                            workflow,
                                                        })
                                                    }
                                                    onShare={(workflow) =>
                                                        setDialog({
                                                            kind: 'shareWorkflow',
                                                            workflow,
                                                        })
                                                    }
                                                    onFork={(workflow) =>
                                                        setDialog({
                                                            kind: 'forkWorkflow',
                                                            workflow,
                                                        })
                                                    }
                                                    sourceFolderId={
                                                        selectedFolderId
                                                    }
                                                    isMobile={isMobile}
                                                    dragDisabled={isSearching}
                                                    location={item.location}
                                                    isHighlighted={
                                                        isSearching &&
                                                        i === highlightedIndex
                                                    }
                                                />
                                            )
                                        )}

                                        {/* Loading skeletons (current folder load, or global search still resolving) */}
                                        {(loadingWorkflows ||
                                            (searchResolving &&
                                                listItems.length === 0)) &&
                                            Array.from({ length: 4 }).map(
                                                (_, index) => (
                                                    <div
                                                        key={`skeleton-row-${index}`}
                                                        className="h-[3.25rem] rounded-xl bg-foreground/[0.03] border border-border/50 dark:border-white/[0.06] animate-pulse"
                                                    />
                                                )
                                            )}

                                        {/* Empty state */}
                                        {!loadingWorkflows &&
                                            !searchResolving &&
                                            listItems.length === 0 && (
                                                <div className="py-12 text-center text-sm text-muted-foreground/60 dark:text-white/30">
                                                    {listSearch.trim()
                                                        ? 'No workflows or folders match your search.'
                                                        : ownershipFilter ===
                                                            'not_owned'
                                                          ? 'Nothing has been shared with you yet.'
                                                          : ownershipFilter ===
                                                              'owned'
                                                            ? "You don't own any workflows or folders yet."
                                                            : 'No workflows yet. Create one to get started.'}
                                                </div>
                                            )}

                                        {/* Keyboard hints while searching */}
                                        {isSearching &&
                                            listItems.length > 0 && (
                                                <div className="flex items-center justify-center gap-4 pt-1 text-[0.6875rem] text-muted-foreground/60 dark:text-white/30 select-none">
                                                    <span className="inline-flex items-center gap-1.5">
                                                        <KeyHint
                                                            keys={[
                                                                'up',
                                                                'down',
                                                            ]}
                                                        />{' '}
                                                        navigate
                                                    </span>
                                                    <span className="inline-flex items-center gap-1.5">
                                                        <KeyHint
                                                            keys={['enter']}
                                                        />{' '}
                                                        open
                                                    </span>
                                                    <span className="inline-flex items-center gap-1.5">
                                                        <KeyHint
                                                            keys={['esc']}
                                                        />{' '}
                                                        clear
                                                    </span>
                                                </div>
                                            )}
                                    </div>
                                ) : (
                                    /* Workflows Grid */
                                    <div
                                        key="workflow-grid"
                                        className="grid gap-3"
                                        style={{
                                            // Cap at 4 columns but step down to 3 / 2 / 1 as the content
                                            // area narrows (both sidebars open, small screen) instead of
                                            // squishing 4 columns. minmax() measures the grid's OWN width,
                                            // so it reacts to container size — not just the viewport
                                            // breakpoint, which can't see the sidebars. Each card stays
                                            // >= 16rem; (100% - 3*0.75rem gap) / 4 keeps the cap at 4.
                                            gridTemplateColumns:
                                                'repeat(auto-fill, minmax(max(16rem, calc((100% - 2.25rem) / 4)), 1fr))',
                                        }}
                                    >
                                        {/* Add New Workflow Card */}
                                        <Card
                                            className={cn(
                                                'border border-border bg-sunken hover:bg-muted/50 dark:hover:bg-zinc-900 h-[17.5rem]',
                                                'hover:border-muted-foreground/40 dark:hover:border-zinc-700 transition-colors duration-200 cursor-pointer group',
                                                isCreatingWorkflow &&
                                                    'opacity-60 pointer-events-none'
                                            )}
                                            onClick={() => {
                                                if (!isCreatingWorkflow)
                                                    createBlankWorkflow();
                                            }}
                                        >
                                            <div className="h-full flex flex-col items-center justify-center text-center space-y-4 p-6">
                                                {isCreatingWorkflow ? (
                                                    <Loader2 className="w-8 h-8 text-muted-foreground dark:text-white/30 animate-spin" />
                                                ) : (
                                                    <Plus
                                                        className="w-8 h-8 text-muted-foreground dark:text-white/30 group-hover:text-foreground transition-colors duration-200"
                                                        strokeWidth={1}
                                                    />
                                                )}
                                                <div className="space-y-1">
                                                    <h3 className="text-sm font-medium text-foreground/80 group-hover:text-foreground transition-colors duration-200">
                                                        New Workflow
                                                    </h3>
                                                    <p className="text-xs text-muted-foreground/80 dark:text-white/30 group-hover:text-muted-foreground transition-colors duration-200">
                                                        Build something great
                                                    </p>
                                                </div>
                                            </div>
                                        </Card>

                                        {/* Folder Cards */}
                                        {filteredFolders.map((folder) => (
                                            <FolderCard
                                                key={folder.id}
                                                folder={folder}
                                                isMultiSelected={selection.isSelected(
                                                    folder.id
                                                )}
                                                isBeingDragged={drag.draggingIds.has(
                                                    folder.id
                                                )}
                                                onClick={(e) => {
                                                    const action =
                                                        selection.handleClick(
                                                            folder.id,
                                                            e
                                                        );
                                                    if (action === 'open')
                                                        setSelectedFolderId(
                                                            folder.id
                                                        );
                                                }}
                                                onSettings={
                                                    handleSettingsFolder
                                                }
                                                onShare={handleShareFolder}
                                                sourceFolderId={
                                                    selectedFolderId
                                                }
                                                isMobile={isMobile}
                                            />
                                        ))}

                                        {/* Loading Skeletons */}
                                        {loadingWorkflows &&
                                            Array.from({ length: 3 }).map(
                                                (_, index) => (
                                                    <WorkflowCardSkeleton
                                                        key={`skeleton-workflow-${index}`}
                                                    />
                                                )
                                            )}

                                        {/* Workflow Cards — rendered during a background (SWR) refresh
                        too, matching the list view, so cards don't vanish on a
                        layout toggle while a folder is reloading. */}
                                        {filteredWorkflows.map(
                                            (workflow: WorkflowApp) => (
                                                <WorkflowCard
                                                    key={workflow.id}
                                                    workflow={workflow}
                                                    isMultiSelected={selection.isSelected(
                                                        workflow.id
                                                    )}
                                                    isBeingDragged={drag.draggingIds.has(
                                                        workflow.id
                                                    )}
                                                    onClick={(e) => {
                                                        const action =
                                                            selection.handleClick(
                                                                workflow.id,
                                                                e
                                                            );
                                                        if (action === 'open')
                                                            handleWorkflowSelect(
                                                                workflow
                                                            );
                                                    }}
                                                    onSettings={(workflow) =>
                                                        setDialog({
                                                            kind: 'editWorkflow',
                                                            workflow,
                                                        })
                                                    }
                                                    onShare={(workflow) =>
                                                        setDialog({
                                                            kind: 'shareWorkflow',
                                                            workflow,
                                                        })
                                                    }
                                                    onFork={(workflow) =>
                                                        setDialog({
                                                            kind: 'forkWorkflow',
                                                            workflow,
                                                        })
                                                    }
                                                    sourceFolderId={
                                                        selectedFolderId
                                                    }
                                                    isMobile={isMobile}
                                                />
                                            )
                                        )}

                                        {/* Empty state — shown for any filter once folders + workflows
                        are empty, mirroring the list view's message so the two
                        layouts give consistent feedback. */}
                                        {!loadingWorkflows &&
                                            filteredFolders.length === 0 &&
                                            filteredWorkflows.length === 0 && (
                                                <div className="col-span-full flex flex-col items-center justify-center py-20 text-muted-foreground dark:text-white/30">
                                                    {ownershipFilter ===
                                                    'not_owned' ? (
                                                        <Share2 className="w-10 h-10 mb-3 text-muted-foreground/70 dark:text-white/30" />
                                                    ) : (
                                                        <Workflow className="w-10 h-10 mb-3 text-muted-foreground/70 dark:text-zinc-600" />
                                                    )}
                                                    <p className="text-sm">
                                                        {ownershipFilter ===
                                                        'not_owned'
                                                            ? 'Nothing has been shared with you yet.'
                                                            : ownershipFilter ===
                                                                'owned'
                                                              ? "You don't own any workflows or folders yet."
                                                              : 'No workflows yet. Create one to get started.'}
                                                    </p>
                                                </div>
                                            )}
                                    </div>
                                )}
                            </div>
                        )}

                        {/*
                         * All dialogs read from the shared `dialog` tagged state. When another
                         * kind opens, setDialog({ kind: '...' }) implicitly closes the current one.
                         * Popups stay mounted and receive isOpen=false so their exit animations play.
                         */}
                        <EditItemPopup
                            item={
                                dialog.kind === 'editWorkflow'
                                    ? dialog.workflow
                                    : null
                            }
                            itemType="Workflow"
                            Icon={Workflow}
                            isOpen={dialog.kind === 'editWorkflow'}
                            onOpenChange={(open) => !open && closeDialog()}
                            onUpdate={handleUpdateWorkflow}
                            onDelete={handleDeleteFromEdit}
                            canEdit={
                                dialog.kind === 'editWorkflow'
                                    ? dialog.workflow.is_owner !== false
                                    : true
                            }
                        />

                        <EditItemPopup
                            item={
                                dialog.kind === 'editFolder'
                                    ? dialog.folder
                                    : null
                            }
                            itemType="Folder"
                            Icon={Folder}
                            isOpen={dialog.kind === 'editFolder'}
                            onOpenChange={(open) => !open && closeDialog()}
                            onUpdate={handleUpdateFolder}
                            onDelete={handleDeleteFolderFromEdit}
                            canEdit={
                                dialog.kind === 'editFolder'
                                    ? dialog.folder.is_owner !== false
                                    : true
                            }
                        />

                        {/* Soft-delete to trash — or, for a shared flow, remove our own access */}
                        <DeleteConfirmPopup
                            itemId={
                                dialog.kind === 'deleteWorkflow'
                                    ? dialog.workflowId
                                    : null
                            }
                            itemType="Workflow"
                            isOpen={dialog.kind === 'deleteWorkflow'}
                            onOpenChange={(open) => !open && closeDialog()}
                            onConfirmDelete={(workflowId) => {
                                if (workflowId) handleDeleteConfirm(workflowId);
                            }}
                            softDelete={true}
                            title={
                                deletingSharedFlow
                                    ? 'Remove shared workflow'
                                    : undefined
                            }
                            confirmLabel={
                                deletingSharedFlow ? 'Remove' : undefined
                            }
                            customMessage={
                                deletingSharedFlow
                                    ? "Remove this workflow from your list? It stays available to the owner and anyone else it's shared with."
                                    : undefined
                            }
                            subText={
                                deletingSharedFlow
                                    ? 'This only removes it from your view — you can rejoin from the original invite link.'
                                    : undefined
                            }
                        />

                        <DeleteConfirmPopup
                            itemId={
                                dialog.kind === 'deleteFolder'
                                    ? dialog.id
                                    : undefined
                            }
                            itemType="Folder"
                            itemName={
                                dialog.kind === 'deleteFolder'
                                    ? dialog.name
                                    : undefined
                            }
                            isOpen={dialog.kind === 'deleteFolder'}
                            onOpenChange={(open) => !open && closeDialog()}
                            onConfirmDelete={handleDeleteFolderConfirm}
                            title={
                                deletingSharedFolder
                                    ? 'Remove shared folder'
                                    : undefined
                            }
                            confirmLabel={
                                deletingSharedFolder ? 'Remove' : undefined
                            }
                            customMessage={
                                deletingSharedFolder
                                    ? "Remove this folder from your list? It stays available to the owner and anyone else it's shared with."
                                    : `Are you sure you want to delete "${dialog.kind === 'deleteFolder' ? dialog.name : ''}"? Workflows inside this folder will be moved to the parent folder.`
                            }
                            subText={
                                deletingSharedFolder
                                    ? 'This only removes it from your view.'
                                    : undefined
                            }
                        />

                        <ShareDialog
                            isOpen={dialog.kind === 'shareWorkflow'}
                            onOpenChange={(open) => !open && closeDialog()}
                            resource={
                                dialog.kind === 'shareWorkflow'
                                    ? dialog.workflow
                                    : null
                            }
                            resourceType="workflow"
                        />

                        <ForkDialog
                            isOpen={dialog.kind === 'forkWorkflow'}
                            onOpenChange={(open) => !open && closeDialog()}
                            resource={
                                dialog.kind === 'forkWorkflow'
                                    ? dialog.workflow
                                    : null
                            }
                            resourceType="workflow"
                            onForkSuccess={handleForkSuccess}
                        />

                        <ShareDialog
                            isOpen={dialog.kind === 'shareFolder'}
                            onOpenChange={(open) => !open && closeDialog()}
                            resource={
                                dialog.kind === 'shareFolder'
                                    ? { id: dialog.id, name: dialog.name }
                                    : null
                            }
                            resourceType="workflow_folder"
                        />
                    </div>
                </div>

                <WorkflowBrowserDragOverlay
                    activeWorkflow={drag.activeWorkflow}
                    activeFolder={drag.activeFolder}
                    dragSource={drag.dragSource}
                    dragPreviewDimensionsRef={drag.dragPreviewDimensionsRef}
                    draggedWorkflowIdsRef={drag.draggedWorkflowIdsRef}
                    draggedFolderIdsRef={drag.draggedFolderIdsRef}
                />
            </DndContext>
            <VideoPopup
                open={!!connectVideo}
                onOpenChange={(open) => {
                    if (!open) setConnectVideo(null);
                }}
                title={connectVideo?.title ?? ''}
                youtubeUrl={connectVideo?.url ?? ''}
            >
                {connectVideo?.type === 'claude' && (
                    <CopyableCode
                        label="MCP Server URL"
                        code={mcpServerUrl()}
                    />
                )}
                {connectVideo?.type === 'claude-code' && (
                    <div className="space-y-3">
                        <CopyableCode
                            label="Add MCP Server"
                            code={`claude mcp add --transport http --scope user noclick ${mcpServerUrl()}`}
                        />
                    </div>
                )}
                {connectVideo?.type === 'chatgpt' && (
                    <CopyableCode
                        label="MCP Server URL"
                        code={mcpServerUrl()}
                    />
                )}
            </VideoPopup>
            <UpgradePopup
                isOpen={!!planLimitError}
                onOpenChange={(open) => {
                    if (!open) setPlanLimitError(null);
                }}
                errorMessage={planLimitError || ''}
            />
        </>
    );
}
