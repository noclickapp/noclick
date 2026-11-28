import {
    useState,
    useCallback,
    useEffect,
    useLayoutEffect,
    useRef,
    useMemo,
} from 'react';
import { useLater } from '@/lib/useLater';
import {
    Plus,
    Workflow,
    Share2,
    Folder,
    FolderPlus,
    Trash2,
    ArrowRight,
    Users,
    User,
    UserPlus,
    ChevronDown,
    Loader2,
} from 'lucide-react';
import { useIsMobile } from '@/ui/useIsMobile';
import { SearchField } from '@/ui/SearchField';
import { cn } from '@/ui/utils';
import { fuzzyFilter } from '@/lib/fuzzySearch';
import { isTextEntryTarget } from '@/lib/keyboard';
import { ShortcutTooltip } from '@/ui/ShortcutTooltip';
import {
    type WorkflowApp,
    type FolderInfoLocal,
} from './useWorkflowBrowserData';
import { useWorkflowBrowserDataContext } from './WorkflowBrowserDataProvider';
import { useNavigate, useLocation } from 'react-router';
import { EditItemPopup } from '@/ui/EditItemPopup';
import { DeleteConfirmPopup } from '@/ui/DeleteConfirmPopup';
import { CreateFolderPopup } from '@/ui/CreateFolderPopup';
import { FolderBreadcrumbs } from './FolderBreadcrumbs';
import { PhoneBarBack, useInPhoneShell } from '@/ui/phoneBar';
import { useGridSelection } from './useGridSelection';
import { useWorkflowBrowserDrag } from './useWorkflowBrowserDrag';
import { DndContext, pointerWithin } from '@dnd-kit/core';
import { WorkflowBrowserDragOverlay } from './WorkflowBrowserDragOverlay';
import {
    WorkflowCardSkeleton,
    DroppableHeaderBar,
    AutomationGrid,
    FolderCard,
    WorkflowCard,
} from './WorkflowBrowserCards';
import { FolderRow, RowList, WorkflowRow } from './WorkflowBrowserList';
import { AutomationBudgetField, AutomationBudgetsHost } from './automationBudget';
import { useListKeyboardNav } from '@/ui/useListKeyboardNav';
import { TrashView } from './TrashView';
import {
    DropdownMenu,
    DropdownMenuTrigger,
    DropdownMenuContent,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
} from '@/ui/dropdown-menu';
import { browserWrites, failureOf } from './workflowBrowserStore';
import { PAGE_TITLE } from '@/ui/titles';
import { useSlot } from '@/slots';
import { ARRIVALS, CANVAS, PLAN_LIMITS, SHARING } from '../slots';
import { anyDialogOpen, useWorkflowsHost, type BrowserAction, type FlowIntent } from './context';
import { useBrowserPreference } from './useBrowserPreference';
import { LayoutToggle, type BrowserLayoutMode } from './LayoutToggle';

// The header's quiet controls: text and icon buttons on the page, no chrome until hovered.
const TOOLBAR_BUTTON =
    'inline-flex h-9 shrink-0 items-center gap-1.5 rounded-full px-3 text-[13px] text-muted-foreground outline-none transition-colors hover:bg-foreground/[0.06] hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring data-[state=open]:bg-foreground/[0.06] data-[state=open]:text-foreground';
const TOOLBAR_ICON_BUTTON =
    'inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-muted-foreground outline-none transition-colors hover:bg-foreground/[0.06] hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring';

// The header's one primary action: a blank automation on the canvas.
function NewWorkflowButton({
    onClick,
    isCreating,
    compact = false,
}: {
    onClick: () => void;
    isCreating: boolean;
    /** A phone's header: just "New". */
    compact?: boolean;
}) {
    return (
        <ShortcutTooltip keys={['N', 'W']}>
            <button
                onClick={() => {
                    if (!isCreating) onClick();
                }}
                disabled={isCreating}
                className="inline-flex h-9 shrink-0 items-center gap-1.5 rounded-full bg-primary pl-3 pr-4 text-[13.5px] font-medium text-primary-foreground transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60"
            >
                {isCreating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" strokeWidth={2.25} />}
                {compact ? 'New' : 'New automation'}
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
                <button className={TOOLBAR_BUTTON} title="Filter by ownership">
                    <ActiveIcon className="h-4 w-4" />
                    <span className="hidden sm:inline">{active.label}</span>
                    <ChevronDown className="h-3.5 w-3.5 opacity-60" />
                </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="min-w-[190px] rounded-xl p-1">
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
                                className="cursor-pointer gap-2.5 rounded-lg py-2 text-[13.5px]"
                            >
                                <Icon className="h-4 w-4 text-muted-foreground" />
                                {o.label}
                            </DropdownMenuRadioItem>
                        );
                    })}
                </DropdownMenuRadioGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    );
}

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
    const later = useLater();
    const location = useLocation();
    const host = useWorkflowsHost();
    // The page's own query parameters beside `workflow`, where its host shares its address with other pages.
    const withAddress = useCallback(
        (params: URLSearchParams) => {
            for (const [name, value] of Object.entries(host.address?.set ?? {})) params.set(name, value);
            return params;
        },
        [host.address]
    );
    const keysHeld = host.keysHeld ?? anyDialogOpen;
    const Canvas = useSlot(CANVAS);
    const sharing = useSlot(SHARING);
    const planLimits = useSlot(PLAN_LIMITS);
    const canShare = sharing.ShareDialog !== null;
    const useArrivals = useSlot(ARRIVALS);

    // Unified store for folders + workflows (IndexedDB-cached, shared with sidebar
    // and the global command palette via WorkflowBrowserDataProvider).
    const store = useWorkflowBrowserDataContext();
    const hiddenSharedWorkflows = store.hiddenSharedCount;
    const workflowTier = store.subscriptionTier;

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
    const [layoutMode, setLayoutMode] = useBrowserPreference<BrowserLayoutMode>(
        scopeId,
        'browserLayoutMode',
        'grid'
    );
    // Ownership filter (anyone / owned by me / shared with me). Persisted per
    // browser, same as layoutMode — it's a local view preference, not shared.
    const [ownershipFilter, setOwnershipFilter] =
        useBrowserPreference<OwnershipFilter>(
            scopeId,
            'browserOwnershipFilter',
            'all'
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
    const [isCreatingWorkflow, setIsCreatingWorkflow] = useState(false);
    const [planLimitError, setPlanLimitError] = useState<string | null>(null);
    const [dialog, setDialog] = useState<Dialog>({ kind: 'none' });
    const closeDialog = useCallback(() => setDialog({ kind: 'none' }), []);
    // Browser key shortcuts: "C" / "L" switch card/list view — but only on the
    // grid, since with a workflow open those keys belong to the canvas (C =
    // nothing, L = logs). Ignored while typing or when a modal is open.
    useEffect(() => {
        const onKey = (e: KeyboardEvent) => {
            if (e.metaKey || e.ctrlKey || e.altKey) return;
            if (isTextEntryTarget(e.target)) return;
            if (keysHeld()) return;
            if (!selectedWorkflow && (e.key === 'c' || e.key === 'C')) {
                e.preventDefault();
                setLayoutMode('grid');
            } else if (!selectedWorkflow && (e.key === 'l' || e.key === 'L')) {
                e.preventDefault();
                setLayoutMode('list');
            }
        };
        document.addEventListener('keydown', onKey);
        return () => document.removeEventListener('keydown', onKey);
    }, [setLayoutMode, selectedWorkflow, keysHeld]);
    const isMobile = useIsMobile();
    const inPhone = useInPhoneShell();
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
                !folderId ? 'Automations' : folderNameById.get(folderId);
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
        scopeId,
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
            const newParams = withAddress(new URLSearchParams(location.search));
            newParams.set('workflow', selectedWorkflow.id);
            navigate(`?${newParams.toString()}`, { replace: true });
        }
    }, [selectedWorkflow, location.search, navigate, withAddress]);

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
            const params = withAddress(new URLSearchParams(location.search));
            params.set('workflow', workflowId);
            for (const name of host.address?.drop ?? []) params.delete(name);
            return params;
        },
        [location.search, withAddress, host.address]
    );

    const handleWorkflowSelect = useCallback(
        (workflow: WorkflowApp) => {
            setSelectedWorkflow(workflow);
            setPendingWorkflowSelect(workflow.id);
            const newParams = buildWorkflowParams(workflow.id);
            later(() => navigate(`?${newParams.toString()}`), 0);
        },
        [navigate, buildWorkflowParams, later]
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
        const newParams = withAddress(new URLSearchParams(location.search));
        newParams.delete('workflow');
        later(() => navigate(`?${newParams.toString()}`), 0);
    }, [navigate, location.search, later, withAddress]);

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

    // Listen for reset event from the sidebar's "Automations" / "G W" - reuse back
    // button logic, and otherwise drop out of a folder or the Trash view back to
    // the top of the grid, so "Go to automations" works from anywhere.
    useEffect(() => {
        const handleReset = () => {
            if (selectedWorkflow) {
                flowCanvasKeyRef.current = null;
                handleBackFromFlowCanvas();
            } else {
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
    }, [selectedWorkflow, handleBackFromFlowCanvas]);

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
            newParams.delete('action');
            navigate(`?${newParams.toString()}`);
        },
        [store, selectedFolderId, buildWorkflowParams, navigate]
    );

    // Reentrancy guard for createBlankWorkflow: a second call can land before the
    // `isCreatingWorkflow` update renders.
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
            const created = await browserWrites.createWorkflow(scopeId, selectedFolderId);
            commitNewWorkflow({ id: created.id, name: created.name, description: created.description || '' });
        } catch (err) {
            console.error('Error creating blank workflow:', err);
            const msg = failureOf(err);
            if (planLimits.isLimit(msg)) setPlanLimitError(msg);
        } finally {
            // Always reset so a later delete (which clears selectedWorkflow) can't
            // revive the full-screen spinner indefinitely.
            creatingWorkflowRef.current = false;
            setIsCreatingWorkflow(false);
        }
    }, [
        scopeId,
        selectedFolderId,
        commitNewWorkflow,
        ownershipFilter,
        setOwnershipFilter,
    ]);


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
                later(() => navigate(`?${newParams.toString()}`), 0);
            }
        },
        [navigate, location.search, later]
    );

    // Single home for the command-palette browser actions (invoked via
    // runFlowIntent). "new-folder" just opens the dialog; "create" makes a blank
    // workflow; "trash" flips the browser to that system view.
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
            createBlankWorkflow();
        },
        [createBlankWorkflow, selectView]
    );

    // External entry points (the global command palette) drive "New workflow" and
    // "New folder" via ?action=create / ?action=new-folder, mirroring the
    // ?action=fork convention. The param is consumed once, then stripped from the
    // URL so it can't re-fire.
    const browserActionHandledRef = useRef(false);
    useEffect(() => {
        const action = new URLSearchParams(location.search).get('action');
        if (action !== 'create' && action !== 'new-folder') {
            browserActionHandledRef.current = false;
            return;
        }
        if (browserActionHandledRef.current) return;

        browserActionHandledRef.current = true;
        if (action === 'create') createBlankWorkflow();
        else setDialog({ kind: 'createFolder' });

        const next = new URLSearchParams(location.search);
        next.delete('action');
        navigate(`?${next.toString()}`, { replace: true });
    }, [location.search, createBlankWorkflow, navigate]);

    // What was handed to the page from elsewhere (a link someone opened, a page that sent them here): its host's.
    const openById = useCallback(
        (workflowId: string) => navigate(`?${buildWorkflowParams(workflowId).toString()}`, { replace: true }),
        [navigate, buildWorkflowParams]
    );
    useArrivals({
        scopeId,
        folderId: selectedFolderId,
        createBlank: createBlankWorkflow,
        openNew: commitNewWorkflow,
        open: openById,
        setMaking: setIsCreatingWorkflow,
        refused: setPlanLimitError,
        showOwned: () => {
            if (ownershipFilter === 'not_owned') setOwnershipFilter('all');
        },
        refreshShared: store.refreshSharedWorkflows,
    });

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
    // FlowCanvas mounts from cache), open a folder, or run a browser action. The palette
    // previously navigate()'d and relied on the URL→useEffect round-trip, which
    // felt slow even when the flow's data was already cached.
    const runFlowIntent = useCallback(
        (intent: FlowIntent) => {
            if (intent.kind === 'open') {
                if (intent.workflow?.id)
                    handleWorkflowClickFromTree(intent.workflow);
            } else if (intent.kind === 'folder') {
                setSelectedFolderId(intent.folderId);
            } else {
                runBrowserAction(intent.action);
            }
        },
        [handleWorkflowClickFromTree, runBrowserAction, setSelectedFolderId]
    );

    // Same-tab fast path: the browser is already mounted on the flow tab, so the
    // noclick:flow-intent event fires here. Clear the latch so the mount effect
    // can't also fire on a later remount.
    useEffect(() => {
        const handleIntent = (e: Event) => {
            host.takePendingIntent?.();
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
        const intent = host.takePendingIntent?.() ?? null;
        if (intent) runFlowIntent(intent);
    }, [runFlowIntent]);

    const handleForkSuccess = useCallback(() => {
        // Refresh the workflow list to show the newly forked workflow
        store.fetchWorkflows(selectedFolderId);
    }, [store, selectedFolderId]);

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
            if (!sharing.leave) {
                rollback();
                alert('Removing something shared with you is done in NoClick.');
                return;
            }
            sharing.leave(resourceType, resourceId).then(
                (left) => {
                    if (!left.removed) {
                        rollback();
                        alert("This is shared with your whole workspace, so it can't be removed individually.");
                    }
                },
                (err: unknown) => {
                    console.error('Failed to leave shared resource:', err);
                    alert(`Failed to remove: ${failureOf(err)}`);
                    rollback();
                }
            );
        },
        [sharing]
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

            browserWrites.deleteFolder(scopeId, folderId).then(
                () => {
                    // Refresh tree + workflows (deleted folder's workflows moved to parent)
                    store.refreshTree();
                    store.fetchWorkflows(selectedFolderId);
                },
                (err) => {
                    console.error('Failed to delete folder:', err);
                    alert(`Failed to delete folder: ${failureOf(err)}`);
                    rollback();
                }
            );
        },
        [
            scopeId,
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
            browserWrites
                .createFolder(scopeId, {
                    name: data.name.trim(),
                    description: data.description.trim(),
                    parentId: selectedFolderId,
                })
                .then(
                    () => {
                        closeDialog();
                        store.refreshTree();
                    },
                    (err) => {
                        console.error('Failed to create folder:', err);
                        alert(`Failed to create folder: ${failureOf(err)}`);
                    }
                )
                .finally(() => setCreatingFolder(false));
        },
        [scopeId, selectedFolderId, store, closeDialog]
    );

    const handleUpdateWorkflow = useCallback(
        (
            workflowId: string,
            updates: { name?: string; description?: string }
        ) => {
            browserWrites.updateWorkflow(workflowId, updates).then(
                () => {
                    store.updateWorkflow(workflowId, {
                        ...(updates.name !== undefined && { name: updates.name }),
                        ...(updates.description !== undefined && { description: updates.description }),
                    });
                    closeDialog();
                },
                (err) => {
                    console.error('Failed to update workflow:', err);
                    alert(`Failed to update workflow: ${failureOf(err)}`);
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
            browserWrites.updateFolder(scopeId, folderId, updates).then(
                (folder) => {
                    store.updateFolder(folderId, {
                        name: folder.name,
                        description: folder.description ?? '',
                    });
                    closeDialog();
                },
                (err) => {
                    console.error('Failed to update folder:', err);
                    alert(`Failed to update folder: ${failureOf(err)}`);
                }
            );
        },
        [scopeId, store, closeDialog]
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

            browserWrites.trashWorkflow(workflowId).catch((err) => {
                console.error('Failed to delete workflow:', err);
                alert(`Failed to delete workflow: ${failureOf(err)}`);
                store.clearRemovalTombstone(workflowId);
                rollback();
            });
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

    // The delete-confirm dialogs double as "remove a shared item": for a not-owned
    // workflow/folder the action unshares (share:leave) instead of deleting, so the
    // copy reflects that. Keyed on the same is_owner lookup the handlers use.
    const deletingSharedFlow =
        dialog.kind === 'deleteWorkflow' &&
        isWorkflowNotOwned(dialog.workflowId);
    const deletingSharedFolder =
        dialog.kind === 'deleteFolder' && isFolderNotOwned(dialog.id);

    const folderPath = selectedFolderId ? store.getFolderPath(selectedFolderId) : [];
    const currentFolder = folderPath[folderPath.length - 1];
    const parentFolder = folderPath[folderPath.length - 2];

    // Nothing here: in a folder, say so; at the root, the two ways to make one.
    const emptyState =
        ownershipFilter === 'not_owned' || selectedFolderId ? (
            <div className="flex flex-col items-center px-6 py-20 text-center">
                <span className="grid h-11 w-11 place-items-center rounded-full bg-foreground/[0.05]">
                    {ownershipFilter === 'not_owned' ? (
                        <Share2 className="h-5 w-5 text-foreground/60" strokeWidth={1.75} />
                    ) : (
                        <Folder className="h-5 w-5 text-foreground/60" strokeWidth={1.75} />
                    )}
                </span>
                <p className="mt-4 text-[15px] font-semibold text-foreground">
                    {ownershipFilter === 'not_owned' ? 'Nothing shared with you yet' : 'This folder is empty'}
                </p>
                <p className="mt-1 max-w-sm text-[14px] leading-relaxed text-muted-foreground">
                    {ownershipFilter === 'not_owned'
                        ? 'Automations and folders others share with you show up here.'
                        : 'Drag automations here, or make a new one.'}
                </p>
            </div>
        ) : (
            <div className="flex flex-col items-center px-6 py-20 text-center">
                <span className="grid h-11 w-11 place-items-center rounded-full bg-foreground/[0.05]">
                    <Workflow className="h-5 w-5 text-foreground/60" strokeWidth={1.75} />
                </span>
                <p className="mt-4 text-[15px] font-semibold text-foreground">
                    {ownershipFilter === 'owned' ? 'You don’t own any automations yet' : 'No automations yet'}
                </p>
                <p className="mt-1 max-w-sm text-[14px] leading-relaxed text-muted-foreground">
                    {host.ask
                        ? 'Tell NoClick what should happen and it builds the automation, or start from a blank canvas.'
                        : 'Start from a blank canvas.'}
                </p>
                <div className="mt-5 flex flex-wrap items-center justify-center gap-2">
                    {host.ask && (
                    <button
                        type="button"
                        onClick={() => host.ask?.('Build me an automation that ')}
                        className="group inline-flex h-9 items-center gap-1.5 rounded-full bg-primary px-4 text-[13.5px] font-medium text-primary-foreground transition-opacity hover:opacity-90"
                    >
                        Ask NoClick
                        <ArrowRight className="h-3.5 w-3.5 transition-transform duration-200 group-hover:translate-x-0.5" />
                    </button>
                    )}
                    <button
                        type="button"
                        onClick={createBlankWorkflow}
                        disabled={isCreatingWorkflow}
                        className="inline-flex h-9 items-center rounded-full px-4 text-[13.5px] text-foreground/85 ring-1 ring-inset ring-border transition-colors hover:bg-foreground/[0.04] hover:text-foreground disabled:opacity-60 dark:ring-foreground/[0.12]"
                    >
                        Blank canvas
                    </button>
                </div>
            </div>
        );

    // The header's actions, shared by the root and folder headers; one row on a phone.
    const headerActions = (
        <div className="flex w-full shrink-0 items-center gap-1 sm:w-auto">
            <OwnershipFilterDropdown value={ownershipFilter} onChange={setOwnershipFilter} />
            <LayoutToggle mode={layoutMode} onChange={setLayoutMode} />
            <ShortcutTooltip label="Trash">
                <button type="button" aria-label="Trash" className={TOOLBAR_ICON_BUTTON} onClick={() => selectView('trash')}>
                    <Trash2 className="h-4 w-4" />
                </button>
            </ShortcutTooltip>
            <ShortcutTooltip label="New folder" keys={['N', 'F']}>
                <button type="button" aria-label="New folder" className={TOOLBAR_ICON_BUTTON} onClick={() => setDialog({ kind: 'createFolder' })}>
                    <FolderPlus className="h-4 w-4" />
                </button>
            </ShortcutTooltip>
            <span className="ml-auto pl-1 sm:ml-1 sm:pl-0">
                <NewWorkflowButton onClick={createBlankWorkflow} isCreating={isCreatingWorkflow} compact={isMobile} />
            </span>
        </div>
    );

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
                    {/* Main Content Area */}
                    <div className="flex-1 h-full overflow-y-auto scrollbar-subtle">
                        {selectedWorkflow ? (
                            /* An open workflow, drawn by whatever its host draws one with */
                            <Canvas
                                key={flowCanvasKeyRef.current || selectedWorkflow.id}
                                workflowTitle={selectedWorkflow.name}
                                workflowId={selectedWorkflow.id}
                                onBack={() => {
                                    flowCanvasKeyRef.current = null; // Clear key when leaving
                                    handleBackFromFlowCanvas();
                                }}
                                onDelete={(wfId) => setDialog({ kind: 'deleteWorkflow', workflowId: wfId })}
                                onTitleChange={(newTitle) => {
                                    handleUpdateWorkflow(selectedWorkflow.id, { name: newTitle });
                                    // Also update the selected workflow state for immediate UI feedback
                                    setSelectedWorkflow({ ...selectedWorkflow, name: newTitle });
                                }}
                                // The name the server holds (the canvas's load): shown, never written back.
                                onTitleShown={(name) =>
                                    setSelectedWorkflow((current) =>
                                        current && current.id === selectedWorkflow.id ? { ...current, name } : current
                                    )
                                }
                                onNavigateToWorkflow={handleNavigateToWorkflow}
                            />
                        ) : viewMode === 'trash' ? (
                            <TrashView isMobile={isMobile} onBack={() => setSelectedFolderId(null)} />
                        ) : (
                            /* Show folder/workflow browser when no workflow is selected */
                            // eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-static-element-interactions -- clicking empty space clears a mouse multi-selection
                            <div
                                className="mx-auto min-h-full w-full max-w-[1240px] px-4 pb-24 pt-3 sm:px-8 sm:pt-10"
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
                                {/* A folder one level down: the phone bar goes back up. */}
                                {inPhone && currentFolder && (
                                    <PhoneBarBack
                                        label={parentFolder?.name ?? 'Automations'}
                                        onBack={() => setSelectedFolderId(parentFolder?.id ?? null)}
                                    />
                                )}
                                <DroppableHeaderBar
                                    folderId={null}
                                    idSuffix="header-root"
                                    // On a phone the list's search sits as far below the actions as the rows sit below it.
                                    className={cn('mb-6 flex-wrap gap-x-4 gap-y-3 rounded-xl px-0 pt-0 sm:mb-7', layoutMode === 'list' && 'max-sm:mb-3')}
                                >
                                    {(currentFolder || !inPhone) && (
                                    <div className="min-w-0 flex-1">
                                        {currentFolder ? (
                                            <>
                                                {!inPhone && (
                                                    <FolderBreadcrumbs
                                                        folderId={selectedFolderId}
                                                        folderPath={folderPath}
                                                        onNavigate={setSelectedFolderId}
                                                        rootLabel="Automations"
                                                        includeCurrent={false}
                                                        className="mb-1 -ml-1"
                                                    />
                                                )}
                                                <h1 className={cn('truncate', PAGE_TITLE)}>
                                                    {currentFolder.name}
                                                </h1>
                                            </>
                                        ) : (
                                            <h1 className={PAGE_TITLE}>Automations</h1>
                                        )}
                                    </div>
                                    )}
                                    {headerActions}
                                </DroppableHeaderBar>

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

                                {/* Shared workflows the plan's limit hides */}
                                {hiddenSharedWorkflows > 0 && (
                                    <planLimits.Notice hidden={hiddenSharedWorkflows} tier={workflowTier} />
                                )}

                                {layoutMode === 'list' ? (
                                    /* Workflows List — compact rows (same handlers/dnd as the grid).
                       Distinct key vs the grid branch below: both branch roots are
                       <div>, so without it React reconciles one into the other on a
                       layout toggle and reuses stale DOM (cards bleed into list view
                       and vice-versa). The key forces a clean unmount/remount. */
                                    <div
                                        key="workflow-list"
                                        className="space-y-3"
                                        ref={listContainerRef}
                                    >
                                        {/* Search — global (folders + workflows across the tree) */}
                                        <SearchField
                                            ref={searchInputRef}
                                            size="lg"
                                            value={listSearch}
                                            onChange={setListSearch}
                                            onKeyDown={handleSearchKeyDown}
                                            placeholder="Search automations and folders"
                                        />

                                        {/* Merged folder + workflow rows, sorted by last edited */}
                                        {listItems.length > 0 && (
                                        <RowList>
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
                                                    onShare={canShare ? () =>
                                                        setDialog({
                                                            kind: 'shareFolder',
                                                            id: item.id,
                                                            name: item.folder
                                                                .name,
                                                        }) : undefined}
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
                                                    onShare={canShare ? (workflow) =>
                                                        setDialog({
                                                            kind: 'shareWorkflow',
                                                            workflow,
                                                        }) : undefined}
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
                                        </RowList>
                                        )}

                                        {/* Loading skeletons (current folder load, or global search still resolving) */}
                                        {listItems.length === 0 && (loadingWorkflows || searchResolving) && (
                                            <RowList>
                                                {Array.from({ length: 4 }).map((_, index) => (
                                                    <div key={`skeleton-row-${index}`} className="flex items-center gap-3 px-4 py-2.5">
                                                        <div className="h-8 w-8 animate-pulse rounded-lg bg-foreground/[0.06]" />
                                                        <div className={cn('h-3.5 animate-pulse rounded bg-foreground/[0.06]', index % 2 ? 'w-1/4' : 'w-1/3')} />
                                                    </div>
                                                ))}
                                            </RowList>
                                        )}

                                        {/* Empty state */}
                                        {!loadingWorkflows &&
                                            !searchResolving &&
                                            listItems.length === 0 &&
                                            (listSearch.trim() ? (
                                                <p className="py-12 text-center text-[14px] text-muted-foreground">
                                                    Nothing matches “{listSearch.trim()}”.
                                                </p>
                                            ) : (
                                                emptyState
                                            ))}

                                    </div>
                                ) : (
                                    /* Workflows Grid */
                                    <AutomationGrid key="workflow-grid" data-testid="automations-grid">
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
                                                onShare={canShare ? handleShareFolder : undefined}
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
                                                    onShare={canShare ? (workflow) =>
                                                        setDialog({
                                                            kind: 'shareWorkflow',
                                                            workflow,
                                                        }) : undefined}
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

                                        {!loadingWorkflows &&
                                            filteredFolders.length === 0 &&
                                            filteredWorkflows.length === 0 && (
                                                <div className="col-span-full">{emptyState}</div>
                                            )}
                                    </AutomationGrid>
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
                            itemType="Automation"
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
                        >
                            {dialog.kind === 'editWorkflow' && dialog.workflow.is_owner !== false && (
                                <AutomationBudgetField workflowId={dialog.workflow.id} />
                            )}
                        </EditItemPopup>
                        {/* An agent's automations show its monthly budget: read once, beside the page. */}
                        <AutomationBudgetsHost />

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
                            itemType="Automation"
                            isOpen={dialog.kind === 'deleteWorkflow'}
                            onOpenChange={(open) => !open && closeDialog()}
                            onConfirmDelete={(workflowId) => {
                                if (workflowId) handleDeleteConfirm(workflowId);
                            }}
                            softDelete={true}
                            title={
                                deletingSharedFlow
                                    ? 'Remove shared automation?'
                                    : undefined
                            }
                            confirmLabel={
                                deletingSharedFlow ? 'Remove' : undefined
                            }
                            customMessage={
                                deletingSharedFlow
                                    ? "Remove this automation from your list? It stays with its owner and anyone else it's shared with."
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
                                    ? 'Remove shared folder?'
                                    : undefined
                            }
                            confirmLabel={
                                deletingSharedFolder ? 'Remove' : undefined
                            }
                            customMessage={
                                deletingSharedFolder
                                    ? "Remove this folder from your list? It stays with its owner and anyone else it's shared with."
                                    : `Delete “${dialog.kind === 'deleteFolder' ? dialog.name : ''}”? The automations in it move up a level.`
                            }
                            subText={
                                deletingSharedFolder
                                    ? 'This only removes it from your view.'
                                    : undefined
                            }
                        />

                        {sharing.ShareDialog && (
                            <sharing.ShareDialog
                                isOpen={dialog.kind === 'shareWorkflow'}
                                onOpenChange={(open) => !open && closeDialog()}
                                resource={dialog.kind === 'shareWorkflow' ? dialog.workflow : null}
                                resourceType="workflow"
                            />
                        )}

                        <sharing.ForkDialog
                            isOpen={dialog.kind === 'forkWorkflow'}
                            onOpenChange={(open) => !open && closeDialog()}
                            resource={dialog.kind === 'forkWorkflow' ? dialog.workflow : null}
                            resourceType="workflow"
                            scopeId={scopeId}
                            onForkSuccess={handleForkSuccess}
                        />

                        {sharing.ShareDialog && (
                            <sharing.ShareDialog
                                isOpen={dialog.kind === 'shareFolder'}
                                onOpenChange={(open) => !open && closeDialog()}
                                resource={dialog.kind === 'shareFolder' ? { id: dialog.id, name: dialog.name } : null}
                                resourceType="workflow_folder"
                            />
                        )}
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
            <planLimits.Refusal message={planLimitError} onClose={() => setPlanLimitError(null)} />
        </>
    );
}
