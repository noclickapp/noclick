// Refactored folder tree sidebar using react-arborist for better performance and maintainability
// Replaces custom tree implementation with library-based approach while preserving all features
// Integrates with WorkflowBrowser for folder/workflow navigation and drag-and-drop

import { useState, useEffect, useRef, useMemo, useCallback, createContext, useContext } from 'react';
import { Tree, NodeRendererProps } from 'react-arborist';
import useResizeObserver from 'use-resize-observer';
import { Plus, Home, Loader2, FolderPlus, Folder, FolderOpen, Settings, Trash2, ChevronLeft, ChevronRight, Search, X, Workflow as WorkflowIcon, ChevronRight as ChevronRightIcon, Share2, ChevronDown } from 'lucide-react';
import { cn } from '~/lib/utils';
import { fuzzyFilter } from '~/utils/fuzzySearch';
import { KeyHint } from '~/components/shared/KeyHint';
import { Button } from '~/components/ui/button';
import { sendEventWithCallback } from '~/lib/socket-sender';
import { useAnalytics } from '~/lib/analytics';
import { EVENTS } from '~/lib/analytics-events';
import type { FolderCreateResponse } from '~/types/socket-events.generated';
import type { TreeNode } from '~/hooks/useWorkflowBrowserData';
import { useDraggableWorkflow } from '~/hooks/useDraggableWorkflow';
import { useDraggableFolder } from '~/hooks/useDraggableFolder';
import { useDroppableFolder } from '~/hooks/useDroppableFolder';
import { useGridSelection } from '~/hooks/useGridSelection';
import { useListKeyboardNav } from '~/hooks/useListKeyboardNav';

// Apple/Vercel-style drop highlight — subtle white wash with soft ring
const DROP_HIGHLIGHT_CLASS = 'bg-foreground/[0.08] ring-1 ring-inset ring-foreground/10';

// Context for multi-select state shared between tree nodes
interface SidebarSelectionContextType {
    isSelected: (id: string) => boolean;
    handleClick: (id: string, event: React.MouseEvent) => 'selected' | 'open';
    clearSelection: () => void;
}
const SidebarSelectionContext = createContext<SidebarSelectionContextType | null>(null);

// TreeNode type imported from useWorkflowBrowserData
export type { TreeNode } from '~/hooks/useWorkflowBrowserData';

interface WorkflowInfo {
    id: string;
    name: string;
    description?: string;
    folder_id?: string | null;
}

interface FolderTreeSidebarProps {
    // Shared data from parent (controlled component)
    treeData: TreeNode[];
    loadingTree: boolean;
    onExpandFolder: (folderId: string) => void;
    // Selection
    selectedFolderId: string | null;
    selectedWorkflowId?: string | null;
    onFolderSelect: (folderId: string | null) => void;
    onFolderShare?: (folderId: string) => void;
    onDeleteFolder?: (folderId: string) => void;
    onCreateSubfolder?: (parentFolderId: string) => void;
    onWorkflowClick?: (workflow: { id: string; name: string; description?: string }) => void;
    isCollapsed?: boolean;
    onToggleCollapse?: () => void;
    onFolderCreated?: (parentFolderId: string | null) => void;
    onSidebarSelection?: (fns: { getSelectedIds: () => string[]; clearSelection: () => void }) => void;
    onTrashSelect?: () => void;
    isTrashView?: boolean;
    className?: string;
}

const DEBOUNCE_DELAY = 300;
const MAX_VISIBLE_RESULTS = 50;

// Generic nav row: pinned, indicator-styled, single-line with icon + label.
// Used by Home / Trash so they read as the same "system" group.
// These sit flush against each other (no inter-row gap) — they're system nav,
// not list items, so the tighter rhythm reads as a coherent group.
function NavRow({
    icon: Icon,
    label,
    isActive,
    isOver = false,
    onClick,
}: {
    icon: typeof Home;
    label: string;
    isActive: boolean;
    isOver?: boolean;
    onClick: () => void;
}) {
    return (
        <div className="relative group cursor-pointer" onClick={onClick}>
            <div
                className={cn(
                    'relative flex items-center gap-2 mx-1.5 px-2.5 h-[28px] rounded-md text-[13px] tracking-tight',
                    isOver
                        ? DROP_HIGHLIGHT_CLASS + ' text-foreground'
                        : isActive
                            ? 'bg-foreground/[0.07] text-foreground font-medium'
                            : 'text-foreground/80 group-hover:bg-foreground/[0.04] group-hover:text-foreground'
                )}
            >
                {isActive && (
                    <div className="absolute left-0 top-1/2 -translate-y-1/2 w-[2px] h-3.5 bg-foreground rounded-r-full" />
                )}
                <Icon className={cn('w-3.5 h-3.5 flex-shrink-0', isActive ? 'text-foreground' : 'text-muted-foreground')} />
                <span>{label}</span>
            </div>
        </div>
    );
}

// Home row — same NavRow visual but also accepts drops (move workflow/folder to root)
function HomeRow({ isActive, onClick }: { isActive: boolean; onClick: () => void }) {
    const { isOver, setNodeRef } = useDroppableFolder({ folderId: null });
    return (
        <div ref={setNodeRef}>
            <NavRow icon={Home} label="Home" isActive={isActive} isOver={isOver} onClick={onClick} />
        </div>
    );
}

// VSCode-style indent guides - absolutely positioned container spanning full row height
// Each guide is an inline-block div with border-left, matching VSCode's .monaco-tl-indent pattern
function IndentGuides({ node }: { node: any }) {
    const guides = [];
    let current = node.parent;
    let level = node.level - 1;

    while (current && level >= 0) {
        if (!current.isLastChild) {
            guides.push(
                <div
                    key={`guide-${level}`}
                    className="absolute top-0 bottom-0 border-l border-border/50 dark:border-white/[0.06]"
                    style={{ left: `${level * 16 + 16}px` }}
                />
            );
        }
        current = current.parent;
        level--;
    }

    if (guides.length === 0) return null;

    return (
        <div className="absolute inset-0 pointer-events-none" style={{ zIndex: 0 }}>
            {guides}
        </div>
    );
}

// Workflow node with drag support + droppable (targets parent folder)
// VSCode behavior: dropping on a child item targets the parent folder
// Supports Cmd/Ctrl+Click toggle and Shift+Click range multi-select via SidebarSelectionContext
function WorkflowNode({ node, style }: { node: any; style: React.CSSProperties }) {
    const sidebarSelection = useContext(SidebarSelectionContext);
    const data = node.data;
    const { attributes, listeners, setNodeRef: setDragRef, isDragging } = useDraggableWorkflow({
        workflowId: data.id,
        workflowName: data.name,
        sourceFolderId: data.folder_id,
        source: 'sidebar',
    });

    // Make this row a drop zone targeting its parent folder
    const parentFolderId = data.folder_id || null;
    const { isOver, setNodeRef: setDropRef } = useDroppableFolder({
        folderId: parentFolderId,
        idSuffix: `wf-${data.id}`,
    });

    // Combine drag and drop refs
    const combinedRef = useCallback((el: HTMLElement | null) => {
        setDragRef(el);
        setDropRef(el);
    }, [setDragRef, setDropRef]);

    const isMultiSelected = sidebarSelection?.isSelected(data.id) ?? false;

    return (
        <div
            ref={combinedRef}
            style={style}
            className={cn(
                'relative h-full group cursor-pointer select-none',
                isDragging && 'opacity-30 scale-[0.98]'
            )}
            data-sidebar-workflow={data.id}
            data-sidebar-selected={isMultiSelected || undefined}
            onClick={(e) => {
                if (e.metaKey || e.ctrlKey || e.shiftKey) {
                    e.preventDefault();
                }
                if (sidebarSelection) {
                    const action = sidebarSelection.handleClick(data.id, e);
                    if (action === 'open') {
                        node.select();
                    }
                } else {
                    node.select();
                }
            }}
            {...attributes}
            {...listeners}
        >
            {/* Indent guides - full row height, never clipped */}
            <IndentGuides node={node} />

            {/* Pill */}
            <div
                className={cn(
                    'relative flex items-center gap-2 h-[24px] my-[2px] mx-1.5 px-2 rounded-md',
                    !isDragging && 'group-hover:bg-foreground/[0.04]',
                    isMultiSelected && !isDragging && 'bg-blue-500/15 group-hover:bg-blue-500/20',
                    !isMultiSelected && node.isSelected && !isOver && 'bg-foreground/[0.07] group-hover:bg-foreground/[0.08]',
                    isOver && DROP_HIGHLIGHT_CLASS,
                )}
                style={{ zIndex: 1 }}
            >
                {/* Left accent — inside the pill so it's perfectly centered with what you see */}
                {(node.isSelected || isMultiSelected) && !isDragging && (
                    <div className={cn(
                        'absolute left-0 top-1/2 -translate-y-1/2 w-[2px] h-3.5 rounded-r-full',
                        isMultiSelected ? 'bg-blue-400' : 'bg-foreground'
                    )} />
                )}
                {/* Workflow Icon */}
                <WorkflowIcon className={cn(
                    node.level === 0 && 'ml-1',
                    'w-3.5 h-3.5 flex-shrink-0',
                    isMultiSelected
                        ? 'text-blue-600 dark:text-blue-400'
                        : node.isSelected
                            ? 'text-orange-600 dark:text-orange-400'
                            : 'text-orange-400/70 group-hover:text-orange-400'
                )} />

                {/* Name */}
                <span
                    className={cn(
                        'text-[13px] truncate flex-1 tracking-tight',
                        isMultiSelected
                            ? 'text-blue-200 font-medium'
                            : node.isSelected ? 'text-foreground font-medium' : 'text-muted-foreground group-hover:text-foreground'
                    )}
                    title={data.description || data.name}
                >
                    {data.name}
                </span>
            </div>
        </div>
    );
}

// Folder node with drop support and VSCode-style UI features
// Auto-expands collapsed folders when a dragged item hovers over them (VSCode behavior)
const FOLDER_AUTO_EXPAND_DELAY = 500; // ms - matches VSCode's delay

function FolderNode({ node, style, onShare, onCreateSubfolder, onDeleteFolder }: {
    node: any;
    style: React.CSSProperties;
    onShare?: (folderId: string) => void;
    onCreateSubfolder?: (parentFolderId: string) => void;
    onDeleteFolder?: (folderId: string) => void;
}) {
    const sidebarSelection = useContext(SidebarSelectionContext);
    const data = node.data;
    const { isOver, setNodeRef: setDropRef, isDraggingWorkflow, isDraggingFolder } = useDroppableFolder({
        folderId: data.id,
        targetFolderPath: data.path,
    });
    const { attributes, listeners, setNodeRef: setDragRef, isDragging } = useDraggableFolder({
        folderId: data.id,
        folderName: data.name,
        parentFolderId: data.parent_folder_id ?? null,
        folderPath: data.path,
        source: 'sidebar',
    });
    const autoExpandTimerRef = useRef<NodeJS.Timeout | null>(null);

    // Merge both refs
    const setNodeRef = (el: HTMLElement | null) => {
        setDropRef(el);
        setDragRef(el);
    };

    // Auto-expand collapsed folders on drag hover (VSCode behavior)
    useEffect(() => {
        if (isOver && !node.isOpen && (isDraggingWorkflow || isDraggingFolder)) {
            autoExpandTimerRef.current = setTimeout(() => {
                node.open();
            }, FOLDER_AUTO_EXPAND_DELAY);
        }
        return () => {
            if (autoExpandTimerRef.current) {
                clearTimeout(autoExpandTimerRef.current);
                autoExpandTimerRef.current = null;
            }
        };
    }, [isOver, node, isDraggingWorkflow, isDraggingFolder]);

    const isMultiSelected = sidebarSelection?.isSelected(data.id) ?? false;

    return (
        <div
            ref={setNodeRef}
            style={style}
            className={cn(
                'relative h-full group cursor-pointer',
                isDragging && 'opacity-30'
            )}
            data-sidebar-folder={data.id}
            data-sidebar-selected={isMultiSelected || undefined}
            onClick={(e) => {
                if (e.metaKey || e.ctrlKey || e.shiftKey) {
                    e.preventDefault();
                }
                if (sidebarSelection) {
                    const action = sidebarSelection.handleClick(data.id, e);
                    if (action === 'open') {
                        node.toggle();
                        node.select();
                    }
                } else {
                    node.toggle();
                    node.select();
                }
            }}
            {...attributes}
            {...listeners}
        >
            {/* Indent guides - full row height, never clipped */}
            <IndentGuides node={node} />

            {/* Pill */}
            <div
                className={cn(
                    'relative flex items-center gap-1.5 h-[24px] my-[2px] mx-1.5 px-1.5 rounded-md',
                    !isDragging && 'group-hover:bg-foreground/[0.04]',
                    isMultiSelected && !isDragging && 'bg-blue-500/15 group-hover:bg-blue-500/20',
                    !isMultiSelected && node.isSelected && !isOver && 'bg-foreground/[0.07] group-hover:bg-foreground/[0.08]',
                    isOver && DROP_HIGHLIGHT_CLASS,
                )}
                style={{ zIndex: 1 }}
            >
                {/* Left accent — inside the pill so it's perfectly centered with what you see */}
                {(node.isSelected || isMultiSelected) && !isDragging && (
                    <div className={cn(
                        'absolute left-0 top-1/2 -translate-y-1/2 w-[2px] h-3.5 rounded-r-full',
                        isMultiSelected ? 'bg-blue-400' : 'bg-foreground'
                    )} />
                )}
                {/* Chevron - always reserve space, show chevron only for expandable folders */}
                <div className="w-4 h-4 flex items-center justify-center flex-shrink-0">
                    {(data.children || data.workflow_count) ? (
                        <button
                            onClick={(e) => {
                                e.stopPropagation();
                                node.toggle();
                            }}
                            className="flex items-center justify-center rounded hover:bg-foreground/[0.06] transition-colors duration-100"
                        >
                            <ChevronRightIcon
                                className={cn(
                                    'w-3.5 h-3.5 text-muted-foreground dark:text-zinc-500 group-hover:text-foreground/80 transition-transform duration-150',
                                    node.isOpen && 'rotate-90'
                                )}
                            />
                        </button>
                    ) : null}
                </div>

                {/* Folder Icon */}
                {node.isOpen ? (
                    <FolderOpen className={cn(
                        'w-[15px] h-[15px] flex-shrink-0',
                        isMultiSelected ? 'text-blue-600 dark:text-blue-400' : 'text-amber-500/80 group-hover:text-amber-400'
                    )} />
                ) : (
                    <Folder className={cn(
                        'w-[15px] h-[15px] flex-shrink-0',
                        isMultiSelected ? 'text-blue-600 dark:text-blue-400' : 'text-amber-500/80 group-hover:text-amber-400'
                    )} />
                )}

                {/* Name */}
                <span
                    className={cn(
                        'text-[13px] truncate flex-1 tracking-tight',
                        isMultiSelected
                            ? 'text-blue-200 font-medium'
                            : node.isSelected ? 'text-foreground font-medium' : 'text-foreground/80 group-hover:text-foreground'
                    )}
                >
                    {data.name}
                </span>

                {/* New Subfolder Button - show on hover, appears to the left of count */}
                {data.is_owner && onCreateSubfolder && (
                    <button
                        onClick={(e) => {
                            e.stopPropagation();
                            onCreateSubfolder(data.id);
                        }}
                        className="hidden group-hover:flex p-1 rounded-md hover:bg-foreground/[0.08] transition-colors"
                        title="New subfolder"
                    >
                        <Plus className="w-3 h-3 text-muted-foreground hover:text-foreground transition-colors" />
                    </button>
                )}

                {/* Share Button - only show for owners on hover, appears to the left of count */}
                {data.is_owner && onShare && (
                    <button
                        onClick={(e) => {
                            e.stopPropagation();
                            onShare(data.id);
                        }}
                        className="hidden group-hover:flex p-1 rounded-md hover:bg-foreground/[0.08] transition-colors"
                        title="Share folder"
                    >
                        <Share2 className="w-3 h-3 text-muted-foreground hover:text-foreground transition-colors" />
                    </button>
                )}

                {/* Delete Button - only show for owners on hover */}
                {data.is_owner && onDeleteFolder && (
                    <button
                        onClick={(e) => {
                            e.stopPropagation();
                            onDeleteFolder(data.id);
                        }}
                        className="hidden group-hover:flex p-1 rounded-md hover:bg-foreground/[0.08] transition-colors"
                        title="Delete folder"
                    >
                        <Trash2 className="w-3 h-3 text-muted-foreground hover:text-red-600 dark:hover:text-red-400 transition-colors" />
                    </button>
                )}

                {/* Workflow Count Badge - only show if count > 0 */}
                {(data.workflow_count ?? 0) > 0 && (
                    <span className="text-[10px] font-medium text-muted-foreground dark:text-zinc-500 px-1.5 py-0.5 rounded-md bg-foreground/[0.04] ml-auto flex-shrink-0 tabular-nums">
                        {data.workflow_count}
                    </span>
                )}

                {/* Loading indicator */}
                {data.isLoading && (
                    <Loader2 className="w-3 h-3 text-muted-foreground dark:text-zinc-500 animate-spin flex-shrink-0" />
                )}
            </div>
        </div>
    );
}

// Custom node renderer that delegates to specific components
// We'll pass callbacks via a factory function instead of directly through props
function createCustomNodeRenderer(
    onShare?: (folderId: string) => void,
    onCreateSubfolder?: (parentFolderId: string) => void,
    onDeleteFolder?: (folderId: string) => void
) {
    return function CustomNode({ node, style, dragHandle }: NodeRendererProps<TreeNode>) {
        const data = node.data;

        if (data.type === 'workflow') {
            return <WorkflowNode node={node} style={style} />;
        }

        if (data.type === 'folder') {
            return <FolderNode node={node} style={style} onShare={onShare} onCreateSubfolder={onCreateSubfolder} onDeleteFolder={onDeleteFolder} />;
        }

        // Fallback for unknown node types (should never reach here)
        console.warn('[CustomNode] Unknown node type:', data.type, data);
        return null;
    };
}

// Collapsed rail for the workspace sidebar. Hover is tracked in JS (not CSS
// :hover) so the tooltip doesn't flash when the rail mounts under a stationary
// cursor after the "[" keyboard toggle — mouseenter only fires on real pointer
// movement. Kept as its own component so each collapse remounts it with a fresh
// (un-hovered) state.
function CollapsedWorkspaceRail({
    className,
    onToggleCollapse,
}: {
    className?: string;
    onToggleCollapse?: () => void;
}) {
    const [hovered, setHovered] = useState(false);
    return (
        <div
            className={cn(
                'relative z-20 h-full bg-sunken border-r border-border/50 dark:border-white/[0.06] flex flex-col cursor-pointer transition-colors',
                hovered && 'bg-foreground/[0.02]',
                className
            )}
            onClick={onToggleCollapse}
            onMouseEnter={() => setHovered(true)}
            onMouseLeave={() => setHovered(false)}
        >
            <div className="p-3 flex justify-center">
                <ChevronRight className="w-5 h-5 text-muted-foreground dark:text-zinc-500" />
            </div>
            {/* bottom-[50vh] anchors the tooltip to the viewport's vertical center.
                The chat rail and this rail have different tops but share the
                viewport bottom edge, so anchoring from the bottom keeps both
                tooltips at the same vertical offset despite their differing heights. */}
            <div
                className={cn(
                    'pointer-events-none absolute left-full bottom-[50vh] z-50 ml-2 flex translate-y-1/2 items-center gap-2 whitespace-nowrap rounded-md border border-border dark:border-white/10 bg-popover dark:bg-[#0a0a0b] px-2.5 py-1.5 text-xs text-foreground shadow-xl dark:shadow-black/60 transition-opacity duration-150',
                    hovered ? 'opacity-100' : 'opacity-0'
                )}
            >
                Show workspace
                <KeyHint keys={['[']} />
            </div>
        </div>
    );
}

export function FolderTreeSidebarArborist({
    treeData: treeDataProp,
    loadingTree,
    onExpandFolder,
    selectedFolderId,
    selectedWorkflowId,
    onFolderSelect,
    onFolderShare,
    onDeleteFolder,
    onCreateSubfolder,
    onWorkflowClick,
    isCollapsed = false,
    onToggleCollapse,
    onFolderCreated,
    onSidebarSelection,
    onTrashSelect,
    isTrashView,
    className,
}: FolderTreeSidebarProps) {
    const { logActivity } = useAnalytics();
    // Tree data comes from parent (useWorkflowBrowserData hook)
    const treeData = treeDataProp;
    const loading = loadingTree;
    const [width, setWidth] = useState(256);
    const [isResizing, setIsResizing] = useState(false);
    const [searchQuery, setSearchQuery] = useState('');
    const [debouncedSearchQuery, setDebouncedSearchQuery] = useState('');
    const [allWorkflows, setAllWorkflows] = useState<WorkflowInfo[]>([]);
    const [loadingWorkflows, setLoadingWorkflows] = useState(false);
    const [showAllResults, setShowAllResults] = useState(false);
    const [showCreateDialog, setShowCreateDialog] = useState(false);
    const [newFolderName, setNewFolderName] = useState('');
    const [creatingFolder, setCreatingFolder] = useState(false);
    const [createUnderParentId, setCreateUnderParentId] = useState<string | null>(null);

    const resizeStartRef = useRef<{ startX: number; startWidth: number }>({ startX: 0, startWidth: 0 });
    const searchInputRef = useRef<HTMLInputElement>(null);
    const debounceTimerRef = useRef<NodeJS.Timeout | null>(null);
    const treeRef = useRef<any>(null);
    // Tracked in a ref (not state) so loadAllWorkflows can stay referentially
    // stable. Reading loadingWorkflows via closure would either re-create the
    // callback (causing the effect that calls it to loop) or read a stale value.
    const isLoadingWorkflowsRef = useRef(false);

    // Measure tree container dimensions for react-arborist
    const {
        ref: treeContainerRef,
        width: containerWidth = 250,
        height: containerHeight = 400,
    } = useResizeObserver<HTMLDivElement>();

    // Multi-select: flatten all tree nodes (folders + workflows) in display order for Shift+Click range
    const flatTreeItems = useMemo(() => {
        const items: { id: string }[] = [];
        const collect = (nodes: TreeNode[]) => {
            for (const n of nodes) {
                items.push({ id: n.id });
                if (n.children) collect(n.children);
            }
        };
        collect(treeData);
        return items;
    }, [treeData]);

    const sidebarSelection = useGridSelection({ items: flatTreeItems });

    // Expose selection to parent for multi-drag integration
    useEffect(() => {
        onSidebarSelection?.({
            getSelectedIds: sidebarSelection.getSelectedArray,
            clearSelection: sidebarSelection.clearSelection,
        });
    }, [onSidebarSelection, sidebarSelection.getSelectedArray, sidebarSelection.clearSelection]);

    // Clear selection when search activates or folder changes
    useEffect(() => {
        if (searchQuery) sidebarSelection.clearSelection();
    }, [searchQuery, sidebarSelection.clearSelection]);

    useEffect(() => {
        sidebarSelection.clearSelection();
    }, [selectedFolderId, sidebarSelection.clearSelection]);

    // Context value for tree node components
    const selectionContextValue = useMemo<SidebarSelectionContextType>(() => ({
        isSelected: sidebarSelection.isSelected,
        handleClick: sidebarSelection.handleClick,
        clearSelection: sidebarSelection.clearSelection,
    }), [sidebarSelection.isSelected, sidebarSelection.handleClick, sidebarSelection.clearSelection]);

    // Handle create subfolder button click
    const handleCreateSubfolderClick = useCallback((parentFolderId: string) => {
        setCreateUnderParentId(parentFolderId);
        setShowCreateDialog(true);
    }, []);

    // Create memoized CustomNode renderer with callbacks
    const CustomNode = useMemo(
        () => createCustomNodeRenderer(onFolderShare, handleCreateSubfolderClick, onDeleteFolder),
        [onFolderShare, handleCreateSubfolderClick, onDeleteFolder]
    );

    // Handle folder creation
    const handleCreateFolder = useCallback(() => {
        if (!newFolderName.trim()) return;

        setCreatingFolder(true);
        sendEventWithCallback(
            {
                event_name: 'workflow_folder:create' as const,
                name: newFolderName,
                description: '',
                parent_folder_id: createUnderParentId,
            },
            (response: FolderCreateResponse) => {
                setCreatingFolder(false);
                if (response.success && response.folder) {
                    logActivity(EVENTS.FOLDER_CREATED, {
                        folder_id: response.folder.id,
                        parent_folder_id: createUnderParentId || 'root',
                        is_subfolder: !!createUnderParentId,
                    });
                    if (onFolderCreated) {
                        onFolderCreated(createUnderParentId);
                    }
                    setNewFolderName('');
                    setShowCreateDialog(false);
                    setCreateUnderParentId(null);
                } else {
                    console.error('Failed to create folder:', response.message);
                    alert(`Failed to create folder: ${response.message}`);
                }
            }
        );
    }, [newFolderName, createUnderParentId, onFolderCreated, logActivity]);

    // Load all workflows globally for search. MUST stay referentially stable
    // (empty deps) — see the comment on isLoadingWorkflowsRef.
    const loadAllWorkflows = useCallback(() => {
        if (isLoadingWorkflowsRef.current) return;
        isLoadingWorkflowsRef.current = true;
        setLoadingWorkflows(true);

        sendEventWithCallback(
            {
                event_name: 'workflow:list' as const,
            } as any,
            (response: any) => {
                isLoadingWorkflowsRef.current = false;
                if (response && response.error) {
                    console.error('Failed to load all workflows:', response.error);
                    setAllWorkflows([]);
                } else if (response.workflows) {
                    const workflows: WorkflowInfo[] = response.workflows.map((wf: any) => ({
                        id: wf.id,
                        name: wf.name,
                        description: wf.description || '',
                        folder_id: wf.folder_id || null,
                    }));
                    setAllWorkflows(workflows);
                } else {
                    setAllWorkflows([]);
                }

                setLoadingWorkflows(false);
            }
        );
    }, []);

    // Debounce search query
    useEffect(() => {
        if (debounceTimerRef.current) {
            clearTimeout(debounceTimerRef.current);
        }

        debounceTimerRef.current = setTimeout(() => {
            setDebouncedSearchQuery(searchQuery);
        }, DEBOUNCE_DELAY);

        return () => {
            if (debounceTimerRef.current) {
                clearTimeout(debounceTimerRef.current);
            }
        };
    }, [searchQuery]);

    // Load workflows when debounced query becomes active
    useEffect(() => {
        if (debouncedSearchQuery.trim() && allWorkflows.length === 0) {
            loadAllWorkflows();
        }
    }, [debouncedSearchQuery, allWorkflows.length, loadAllWorkflows]);

    // Tree data and mutations are now managed by parent via useWorkflowBrowserData hook.
    // No local fetch/move functions needed — parent's store handles everything.

    // Helper functions for search
    const handleClearSearch = useCallback(() => {
        setSearchQuery('');
        setDebouncedSearchQuery('');
        setAllWorkflows([]); // Free memory
        setShowAllResults(false);
    }, []);

    const handleSearchChange = useCallback((value: string) => {
        setSearchQuery(value);
        setShowAllResults(false);
    }, []);

    // Find folder name by ID recursively through tree structure
    const findFolderName = useCallback((folderId: string, nodes: TreeNode[]): string | null => {
        for (const node of nodes) {
            if (node.type === 'folder' && node.id === folderId) return node.name;
            if (node.children) {
                const found = findFolderName(folderId, node.children);
                if (found) return found;
            }
        }
        return null;
    }, []);

    const getFolderNameById = useCallback((folderId: string | null | undefined): string => {
        if (!folderId) return 'Root';
        const folderName = findFolderName(folderId, treeData);
        return folderName || 'Unknown Folder';
    }, [findFolderName, treeData]);

    // Highlight search term in text
    const highlightText = useCallback((text: string, query: string) => {
        if (!query.trim()) return text;
        const parts = text.split(new RegExp(`(${query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi'));
        return parts.map((part, index) =>
            part.toLowerCase() === query.toLowerCase() ? (
                <span key={index} className="bg-yellow-500/20 text-yellow-600 dark:text-yellow-400">{part}</span>
            ) : (
                <span key={index}>{part}</span>
            )
        );
    }, []);

    // Handle workflow click from search results - select and close search
    const handleWorkflowClick = useCallback((workflow: WorkflowInfo) => {
        onWorkflowClick?.({ id: workflow.id, name: workflow.name, description: workflow.description });
        handleClearSearch();
    }, [onWorkflowClick, handleClearSearch]);

    // Filter and prioritize workflows based on search query
    const filteredWorkflows = useMemo(() => {
        if (!debouncedSearchQuery.trim()) return [];

        return fuzzyFilter(allWorkflows, debouncedSearchQuery, workflow => [
            { text: workflow.name.toLowerCase(), weight: 1, fuzzy: true },
            { text: (workflow.description ?? '').toLowerCase(), weight: 0.4 },
        ]);
    }, [allWorkflows, debouncedSearchQuery]);

    const visibleWorkflows = showAllResults ? filteredWorkflows : filteredWorkflows.slice(0, MAX_VISIBLE_RESULTS);
    const hasMoreResults = filteredWorkflows.length > MAX_VISIBLE_RESULTS;
    const isSearchActive = debouncedSearchQuery.trim().length > 0;

    // Keyboard navigation for search results — shared with the workflow browser
    // list via useListKeyboardNav.
    const {
        index: selectedResultIndex,
        setIndex: setSelectedResultIndex,
        handleKeyDown: handleSearchKeyDown,
    } = useListKeyboardNav({
        count: visibleWorkflows.length,
        active: isSearchActive,
        onSelect: (i) => {
            if (visibleWorkflows[i]) handleWorkflowClick(visibleWorkflows[i]);
        },
        onEscape: handleClearSearch,
    });

    // Reset the highlight whenever the query changes.
    useEffect(() => {
        setSelectedResultIndex(0);
    }, [searchQuery, setSelectedResultIndex]);

    // Scroll selected search result into view — only when the keyboard-driven
    // index changes, NOT on every render. Depending on `visibleWorkflows` here
    // re-fired the effect every keystroke (new slice() reference each render),
    // restarting smooth-scroll animations and producing visible flicker.
    useEffect(() => {
        if (selectedResultIndex < 0) return;
        const element = document.getElementById(`search-result-${selectedResultIndex}`);
        element?.scrollIntoView({ block: 'nearest' });
    }, [selectedResultIndex]);

    // Clear react-arborist's internal selection when the view switches to a
    // non-tree mode (trash), or when the parent clears the selected workflow.
    // Without this, the tree keeps the last clicked row visually highlighted
    // even though we've navigated away.
    useEffect(() => {
        if (isTrashView) {
            treeRef.current?.deselectAll?.();
        }
    }, [isTrashView]);

    useEffect(() => {
        if (!selectedWorkflowId && !selectedFolderId) {
            treeRef.current?.deselectAll?.();
        }
    }, [selectedWorkflowId, selectedFolderId]);

    // Resize handlers
    const handleResizeStart = (e: React.MouseEvent) => {
        e.preventDefault();
        setIsResizing(true);
        resizeStartRef.current = {
            startX: e.clientX,
            startWidth: width,
        };
    };

    useEffect(() => {
        if (!isResizing) return;

        const handleMouseMove = (e: MouseEvent) => {
            const deltaX = e.clientX - resizeStartRef.current.startX;
            const newWidth = Math.max(200, Math.min(600, resizeStartRef.current.startWidth + deltaX));
            setWidth(newWidth);
        };

        const handleMouseUp = () => {
            setIsResizing(false);
        };

        document.addEventListener('mousemove', handleMouseMove);
        document.addEventListener('mouseup', handleMouseUp);

        return () => {
            document.removeEventListener('mousemove', handleMouseMove);
            document.removeEventListener('mouseup', handleMouseUp);
        };
    }, [isResizing]);

    if (isCollapsed) {
        return (
            <CollapsedWorkspaceRail
                className={className}
                onToggleCollapse={onToggleCollapse}
            />
        );
    }

    return (
        <div
            className={cn('h-full bg-sunken border-r border-border/50 dark:border-white/[0.06] flex flex-col relative', className)}
            style={{ width: `${width}px` }}
        >
            {/* Header */}
            <div className="px-3 pt-3 pb-2 flex items-center justify-between gap-2 flex-shrink-0">
                <div className="flex items-center gap-2 flex-1 min-w-0">
                    <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground dark:text-zinc-500 truncate">Workspace</span>
                </div>
                <div className="flex items-center gap-0.5 flex-shrink-0">
                    <button
                        onClick={() => {
                            setCreateUnderParentId(null);
                            setShowCreateDialog(true);
                        }}
                        title="New folder"
                        className="h-6 w-6 p-0 flex items-center justify-center text-muted-foreground dark:text-zinc-500 hover:bg-foreground/[0.06] hover:text-foreground rounded-md transition-colors"
                    >
                        <FolderPlus className="w-3.5 h-3.5" />
                    </button>
                    <button
                        onClick={onToggleCollapse}
                        title="Collapse sidebar"
                        className="h-6 w-6 p-0 flex items-center justify-center text-muted-foreground dark:text-zinc-500 hover:bg-foreground/[0.06] hover:text-foreground rounded-md transition-colors"
                    >
                        <ChevronLeft className="w-4 h-4" />
                    </button>
                </div>
            </div>

            {/* Search Bar */}
            <div className="px-3 pb-2 flex-shrink-0">
                <div className="relative group">
                    <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground dark:text-zinc-500 group-focus-within:text-foreground/80 transition-colors" />
                    <input
                        ref={searchInputRef}
                        type="text"
                        placeholder="Search workflows"
                        value={searchQuery}
                        onChange={(e) => handleSearchChange(e.target.value)}
                        onKeyDown={handleSearchKeyDown}
                        className="w-full h-8 pl-8 pr-8 text-[13px] bg-foreground/[0.03] border border-border/50 dark:border-white/[0.06] rounded-lg text-foreground placeholder:text-[hsl(var(--placeholder))] focus:outline-none focus:bg-foreground/[0.05] focus:border-border dark:focus:border-white/15"
                    />
                    {searchQuery && (
                        <button
                            onClick={handleClearSearch}
                            className="absolute right-1.5 top-1/2 -translate-y-1/2 p-1 hover:bg-foreground/[0.06] rounded-md"
                            title="Clear search (Esc)"
                        >
                            <X className="w-3 h-3 text-muted-foreground" />
                        </button>
                    )}
                </div>
                {searchQuery && searchQuery !== debouncedSearchQuery && (
                    <div className="text-[10px] text-muted-foreground dark:text-zinc-500 mt-1.5 px-2">Searching…</div>
                )}
            </div>

            {/* Search Results */}
            {isSearchActive && (
                <div className="px-3 pb-2 flex-shrink-0">
                    <div className="text-[11px] text-muted-foreground dark:text-zinc-500 px-2 pb-1.5 flex items-center justify-between">
                        <div className="flex items-center gap-1.5">
                            {loadingWorkflows ? (
                                <>
                                    <Loader2 className="w-3 h-3 animate-spin" />
                                    <span>Searching…</span>
                                </>
                            ) : (
                                <span className="font-medium tracking-wide">
                                    {filteredWorkflows.length} workflow{filteredWorkflows.length !== 1 ? 's' : ''}
                                </span>
                            )}
                        </div>
                        {!loadingWorkflows && filteredWorkflows.length > 0 && (
                            <span className="text-[10px] text-muted-foreground/70 dark:text-zinc-600">↑↓ ⏎</span>
                        )}
                    </div>
                    <div className="space-y-0.5 max-h-80 overflow-y-auto scrollbar-subtle">
                        {visibleWorkflows.map((workflow, index) => {
                            const folderName = getFolderNameById(workflow.folder_id);
                            const isSelected = selectedResultIndex === index;
                            return (
                                <div
                                    key={workflow.id}
                                    id={`search-result-${index}`}
                                    className={cn(
                                        'flex items-start gap-2 px-2 py-1.5 rounded-md cursor-pointer transition-colors',
                                        isSelected ? 'bg-foreground/[0.07]' : 'hover:bg-foreground/[0.04]',
                                        selectedWorkflowId === workflow.id && 'ring-1 ring-blue-500/40'
                                    )}
                                    onClick={() => handleWorkflowClick(workflow)}
                                    onMouseEnter={() => setSelectedResultIndex(index)}
                                    title={`${workflow.name}${workflow.description ? '\n' + workflow.description : ''}\nLocation: ${folderName}`}
                                >
                                    <WorkflowIcon className="w-3.5 h-3.5 text-orange-400/80 flex-shrink-0 mt-0.5" />
                                    <div className="flex-1 min-w-0">
                                        <div className="text-[13px] text-foreground truncate font-medium tracking-tight">
                                            {highlightText(workflow.name, debouncedSearchQuery)}
                                        </div>
                                        <div className="flex items-center gap-1 mt-0.5">
                                            {folderName === 'Root' ? (
                                                <Home className="w-2.5 h-2.5 text-muted-foreground dark:text-zinc-500" />
                                            ) : (
                                                <Folder className="w-2.5 h-2.5 text-muted-foreground dark:text-zinc-500" />
                                            )}
                                            <span className="text-[10px] text-muted-foreground truncate">
                                                {folderName}
                                            </span>
                                        </div>
                                        {workflow.description && (
                                            <div className="text-[10px] text-muted-foreground dark:text-zinc-500 truncate mt-0.5">
                                                {highlightText(workflow.description, debouncedSearchQuery)}
                                            </div>
                                        )}
                                    </div>
                                </div>
                            );
                        })}

                        {/* Show More Button */}
                        {hasMoreResults && !showAllResults && (
                            <button
                                onClick={() => setShowAllResults(true)}
                                className="w-full px-2 py-2 text-[12px] text-muted-foreground hover:text-foreground hover:bg-foreground/[0.04] rounded-md transition-colors flex items-center justify-center gap-1.5"
                            >
                                <ChevronDown className="w-3 h-3" />
                                Show {filteredWorkflows.length - MAX_VISIBLE_RESULTS} more
                            </button>
                        )}

                        {/* Empty State - No Results */}
                        {!loadingWorkflows && filteredWorkflows.length === 0 && allWorkflows.length > 0 && (
                            <div className="text-center py-8 px-2">
                                <p className="text-[12px] text-foreground/80 font-medium">No workflows match &quot;{debouncedSearchQuery}&quot;</p>
                                <p className="text-[10px] text-muted-foreground dark:text-zinc-500 mt-2">
                                    Searched {allWorkflows.length} workflow{allWorkflows.length !== 1 ? 's' : ''}
                                </p>
                                <p className="text-[10px] text-muted-foreground dark:text-zinc-500 mt-1">
                                    Try a different search term
                                </p>
                            </div>
                        )}

                        {/* Empty State - No Workflows */}
                        {!loadingWorkflows && allWorkflows.length === 0 && (
                            <div className="text-center py-8 px-2">
                                <p className="text-[12px] text-foreground/80 font-medium">No workflows found</p>
                                <p className="text-[10px] text-muted-foreground dark:text-zinc-500 mt-2">
                                    Create a workflow to get started
                                </p>
                            </div>
                        )}
                    </div>
                </div>
            )}

            {/* Create Folder Dialog */}
            {showCreateDialog && (
                <div className="px-3 pt-2 pb-3 border-b border-border/50 dark:border-white/[0.06]">
                    <div className="space-y-2 p-2 bg-foreground/[0.03] rounded-lg border border-border/50 dark:border-white/[0.06] shadow-sm">
                        <input
                            type="text"
                            placeholder="Folder name"
                            value={newFolderName}
                            onChange={(e) => setNewFolderName(e.target.value)}
                            onKeyDown={(e) => {
                                if (e.key === 'Enter') handleCreateFolder();
                                if (e.key === 'Escape') {
                                    setShowCreateDialog(false);
                                    setCreateUnderParentId(null);
                                    setNewFolderName('');
                                }
                            }}
                            className="w-full px-2.5 py-1.5 text-[13px] bg-foreground/[0.04] border border-border/50 dark:border-white/[0.06] rounded-md text-foreground placeholder:text-[hsl(var(--placeholder))] focus:outline-none focus:border-border dark:focus:border-white/15 focus:bg-foreground/[0.06] transition-all"
                            autoFocus
                        />
                        <div className="flex gap-2">
                            <Button
                                size="sm"
                                onClick={handleCreateFolder}
                                disabled={!newFolderName.trim() || creatingFolder}
                                className="flex-1 h-7 bg-primary text-primary-foreground hover:bg-primary/90 disabled:bg-foreground/10 disabled:text-muted-foreground dark:disabled:text-zinc-500 rounded-md text-[12px] font-medium"
                            >
                                {creatingFolder ? (
                                    <Loader2 className="w-3 h-3 animate-spin" />
                                ) : (
                                    <FolderPlus className="w-3 h-3 mr-1" />
                                )}
                                Create
                            </Button>
                            <Button
                                size="sm"
                                variant="ghost"
                                onClick={() => {
                                    setShowCreateDialog(false);
                                    setNewFolderName('');
                                    setCreateUnderParentId(null);
                                }}
                                className="h-7 text-muted-foreground hover:bg-foreground/[0.06] hover:text-foreground rounded-md text-[12px]"
                            >
                                Cancel
                            </Button>
                        </div>
                    </div>
                </div>
            )}

            {/* System nav (Home / Trash) + Tree - hidden during search */}
            {!isSearchActive && (
                <>
                    <div className="flex-shrink-0">
                        <HomeRow
                            isActive={selectedFolderId === null && !isTrashView}
                            onClick={() => onFolderSelect(null)}
                        />
                        {onTrashSelect && (
                            <NavRow
                                icon={Trash2}
                                label="Trash"
                                isActive={!!isTrashView}
                                onClick={onTrashSelect}
                            />
                        )}
                    </div>

                    {/* Subtle divider between system nav and the tree */}
                    {treeData.length > 0 && (
                        <div className="mx-3 my-2 border-t border-border/50 dark:border-white/[0.06] flex-shrink-0" />
                    )}

                    <div ref={treeContainerRef} className="flex-1 overflow-hidden [&>div]:scrollbar-subtle">
                        {loading && treeData.length === 0 ? (
                            <div className="flex items-center justify-center h-32">
                                <Loader2 className="w-5 h-5 text-muted-foreground dark:text-zinc-500 animate-spin" />
                            </div>
                        ) : !loading && treeData.length === 0 ? (
                            <div className="flex flex-col items-center justify-center h-full px-6 text-center gap-2">
                                <div className="w-10 h-10 rounded-full bg-foreground/[0.04] flex items-center justify-center">
                                    <FolderPlus className="w-4 h-4 text-muted-foreground dark:text-zinc-500" />
                                </div>
                                <p className="text-[12px] text-muted-foreground font-medium tracking-tight">No folders yet</p>
                                <button
                                    onClick={() => {
                                        setCreateUnderParentId(null);
                                        setShowCreateDialog(true);
                                    }}
                                    className="text-[11px] text-muted-foreground dark:text-zinc-500 hover:text-foreground transition-colors"
                                >
                                    Create your first folder
                                </button>
                            </div>
                        ) : containerHeight > 0 && containerWidth > 0 ? (
                            <SidebarSelectionContext.Provider value={selectionContextValue}>
                                <Tree
                                    ref={treeRef}
                                    data={treeData}
                                    openByDefault={false}
                                    disableDrag={true}
                                    disableDrop={true}
                                    width={containerWidth}
                                    height={containerHeight}
                                    indent={16}
                                    rowHeight={28}
                                    overscanCount={10}
                                    paddingTop={0}
                                    paddingBottom={8}
                                    onSelect={(selected) => {
                                        const node = selected[0];
                                        if (node?.data.type === 'folder') {
                                            onFolderSelect(node.data.id);
                                        } else if (node?.data.type === 'workflow') {
                                            onWorkflowClick?.({ id: node.data.id, name: node.data.name, description: node.data.description });
                                        }
                                    }}
                                    onToggle={(id) => {
                                        // Load workflows when folder is expanded (via parent's store)
                                        const node = treeRef.current?.get(id);
                                        if (node?.data.type === 'folder' && node.isOpen && !node.data.children?.some((c: TreeNode) => c.type === 'workflow')) {
                                            onExpandFolder(node.data.id);
                                        }
                                    }}
                                >
                                    {CustomNode}
                                </Tree>
                            </SidebarSelectionContext.Provider>
                        ) : null}
                    </div>
                </>
            )}

            {/* Resize handle */}
            <div
                className={cn(
                    'absolute right-0 top-0 bottom-0 w-px cursor-ew-resize transition-colors',
                    'hover:bg-foreground/20 hover:w-[2px]',
                    isResizing && 'bg-blue-500/70 w-[2px]'
                )}
                onMouseDown={handleResizeStart}
            />
        </div>
    );
}
