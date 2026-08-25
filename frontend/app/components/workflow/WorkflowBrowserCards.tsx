import { useCallback, useRef } from 'react';
import { Card } from '~/components/ui/card';
import {
    Clock,
    Folder,
    GitFork,
    Settings,
    Share2,
    User,
    Workflow,
} from 'lucide-react';
import { useDraggable } from '@dnd-kit/core';
import { CarbonGradient } from '~/components/shared/CarbonGradient';
import { WorkflowGraphPreview } from '~/components/workflow/WorkflowGraphPreview';
import {
    workflowIconTypes,
    isWorkflowIconType,
} from '~/lib/workflowBrowserStore';
import { cn } from '~/lib/utils';
import { useDroppableFolder } from '~/hooks/useDroppableFolder';
import { NodeIconStack } from '~/components/shared/NodeIconStack';
import { getNodeIconData } from '~/lib/nodeIconRegistry';
import type {
    WorkflowApp,
    FolderInfoLocal,
} from '~/hooks/useWorkflowBrowserData';

type FolderInfo = FolderInfoLocal;

// Compact relative-time formatter — "just now", "5m ago", "2d ago", "3mo ago".
// Used in the card pill where horizontal space is tight. Falls back to '' so
// callers can `&&`-gate the segment. Exported so the list-view rows
// (WorkflowBrowserList) render identical metadata without duplicating logic.
export function relativeShort(iso?: string): string {
    if (!iso) return '';
    const ts = new Date(iso).getTime();
    if (!Number.isFinite(ts)) return '';
    const sec = (Date.now() - ts) / 1000;
    if (sec < 60) return 'just now';
    if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
    if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
    if (sec < 86400 * 30) return `${Math.floor(sec / 86400)}d ago`;
    if (sec < 86400 * 365) return `${Math.floor(sec / (86400 * 30))}mo ago`;
    return `${Math.floor(sec / (86400 * 365))}y ago`;
}

// Leading text for the workflow pill — owner name when shared, otherwise
// the node count. Owner is load-bearing context so it takes priority on
// shared cards; node count lands in the time pill's tooltip in that case.
export function formatWorkflowLeadingPill(w: WorkflowApp): string {
    if (w.is_owner === false && w.owner_name) return w.owner_name;
    if (typeof w.node_count !== 'number') return 'Workflow';
    return `${w.node_count} ${w.node_count === 1 ? 'node' : 'nodes'}`;
}

export function formatWorkflowMetaTooltip(w: WorkflowApp): string {
    const lines: string[] = [];
    if (typeof w.node_count === 'number') {
        lines.push(`${w.node_count} ${w.node_count === 1 ? 'node' : 'nodes'}`);
    }
    if (w.updated_at)
        lines.push(`Edited ${new Date(w.updated_at).toLocaleString()}`);
    if (w.created_at)
        lines.push(`Created ${new Date(w.created_at).toLocaleString()}`);
    if (w.is_owner === false && w.owner_name)
        lines.push(`Owner: ${w.owner_name}`);
    return lines.join('\n');
}

export const WorkflowCardSkeleton = () => (
    <Card className="bg-card shadow-sm dark:shadow-none dark:bg-card/50 backdrop-blur-sm border-border/70 dark:border-border/50 animate-pulse h-[17.5rem] overflow-hidden">
        {/* Image section skeleton */}
        <div className="h-[11.25rem] bg-muted"></div>

        {/* Content section skeleton */}
        <div className="h-[6.25rem] p-4 flex flex-col justify-between">
            <div className="space-y-1">
                <div className="h-4 bg-muted-foreground/30 dark:bg-zinc-700 rounded w-3/4"></div>
                <div className="h-3 bg-muted-foreground/30 dark:bg-zinc-700 rounded w-full"></div>
                <div className="h-3 bg-muted-foreground/30 dark:bg-zinc-700 rounded w-5/6"></div>
            </div>
        </div>
    </Card>
);

// Droppable header bar — wraps the breadcrumb/header row as a large drop zone for moving items to root
export function DroppableHeaderBar({
    folderId,
    idSuffix,
    children,
    className,
}: {
    folderId: string | null;
    idSuffix: string;
    children: React.ReactNode;
    className?: string;
}) {
    const { isOver, setNodeRef } = useDroppableFolder({ folderId, idSuffix });

    return (
        <div
            ref={setNodeRef}
            className={cn(
                'flex items-center justify-between pl-1 pr-3 pt-2.5 pb-0 rounded-lg transition-colors',
                isOver && 'bg-blue-600/20 ring-1 ring-blue-400/50',
                className
            )}
        >
            {children}
        </div>
    );
}

interface FolderCardProps {
    folder: FolderInfo;
    onClick: (e: React.MouseEvent) => void;
    onSettings?: (folderId: string) => void;
    onShare?: (folderId: string) => void;
    isMultiSelected?: boolean;
    isBeingDragged?: boolean;
    sourceFolderId?: string | null;
    isMobile?: boolean;
}

export const FolderCard = ({
    folder,
    onClick,
    onSettings,
    onShare,
    isMultiSelected,
    isBeingDragged,
    sourceFolderId,
    isMobile,
}: FolderCardProps) => {
    // Only owners can move/share a folder; not-owned (shared) folders are
    // read-only here — surfaced in "Owned by anyone" but their mutating
    // affordances would be rejected server-side.
    const canManage = folder.is_owner !== false;
    const { isOver, setNodeRef: setDropRef } = useDroppableFolder({
        folderId: folder.id,
        idSuffix: 'card',
        targetFolderPath: folder.path,
    });
    const {
        attributes,
        listeners,
        setNodeRef: setDragRef,
        isDragging,
    } = useDraggable({
        id: `folder-drag-grid-${folder.id}`,
        disabled: isMobile || !canManage,
        data: {
            type: 'folder',
            folderId: folder.id,
            folderName: folder.name,
            parentFolderId: sourceFolderId,
            folderPath: folder.path,
            source: 'grid',
        },
    });

    // Merge drag + drop refs onto the same DOM node
    const mergedRef = useCallback(
        (node: HTMLDivElement | null) => {
            setDragRef(node);
            setDropRef(node);
        },
        [setDragRef, setDropRef]
    );

    return (
        <Card
            ref={mergedRef}
            {...attributes}
            {...listeners}
            data-folder-card
            className={cn(
                'bg-card shadow-sm hover:shadow-md dark:shadow-none dark:hover:shadow-none dark:bg-card/50 backdrop-blur-sm border-border/70 dark:border-border/50 dark:hover:bg-card/60 transition-all cursor-pointer group',
                'relative overflow-hidden h-[17.5rem]',
                isOver &&
                    'bg-blue-600/40 border-2 border-blue-400 shadow-lg shadow-blue-500/30 scale-[1.02] ring-2 ring-blue-500/20',
                (isDragging || isBeingDragged) && 'opacity-30 scale-95',
                isMultiSelected && 'ring-2 ring-blue-500/70'
            )}
            onClick={onClick}
        >
            {/* Action buttons - positioned over the image */}
            <div className="absolute top-2 right-2 flex items-center gap-1.5 z-10">
                {onShare && canManage && (
                    <button
                        onClick={(e) => {
                            e.stopPropagation();
                            onShare(folder.id);
                        }}
                        className="p-2 rounded-full bg-card/80 border border-border dark:bg-black/60 dark:border-0 backdrop-blur-sm hover:bg-accent dark:hover:bg-zinc-700 transition-colors group/button min-w-9 min-h-9 flex items-center justify-center"
                        title="Share"
                    >
                        <Share2 className="w-4 h-4 text-muted-foreground dark:text-foreground/80 group-hover/button:text-foreground transition-colors" />
                    </button>
                )}
                {onSettings && (
                    <button
                        onClick={(e) => {
                            e.stopPropagation();
                            onSettings(folder.id);
                        }}
                        className="p-2 rounded-full bg-card/80 border border-border dark:bg-black/60 dark:border-0 backdrop-blur-sm hover:bg-accent dark:hover:bg-zinc-700 transition-colors group/button min-w-9 min-h-9 flex items-center justify-center"
                        title="Settings"
                    >
                        <Settings className="w-4 h-4 text-muted-foreground dark:text-foreground/80 group-hover/button:text-foreground transition-colors" />
                    </button>
                )}
            </div>

            {/* Folder Preview Section */}
            <div className="h-[11.25rem] relative overflow-hidden bg-gradient-to-br from-yellow-900/20 to-card/50">
                <div className="absolute inset-0 flex items-center justify-center">
                    <Folder className="w-24 h-24 text-yellow-600/40 group-hover:text-yellow-600/60 transition-colors" />
                </div>

                {/* Folder badge - bottom left */}
                <div className="absolute bottom-2 left-2 z-10">
                    <div className="flex items-center gap-1.5 px-2 py-1 rounded-full bg-card/80 border border-border dark:bg-black/60 dark:border-0 backdrop-blur-sm">
                        <Folder className="w-3.5 h-3.5 text-yellow-600/80" />
                        <span className="text-[0.625rem] text-foreground/80 max-w-[6.25rem] truncate">
                            {folder.is_owner === false && folder.owner_name
                                ? folder.owner_name
                                : 'Folder'}
                        </span>
                    </div>
                </div>

                {/* Workflow count badge - bottom right */}
                {folder.workflow_count > 0 && (
                    <div className="absolute bottom-2 right-2 z-10">
                        <span className="text-[0.625rem] px-2 py-1 rounded-full backdrop-blur-sm bg-blue-600/40 text-blue-700 dark:text-blue-300">
                            {folder.workflow_count} workflow
                            {folder.workflow_count !== 1 ? 's' : ''}
                        </span>
                    </div>
                )}
            </div>

            {/* Content Section */}
            <div className="h-[6.25rem] p-4">
                <div className="space-y-1">
                    <h3 className="text-sm font-medium text-foreground/80 group-hover:text-foreground line-clamp-1 break-all">
                        {folder.name}
                    </h3>
                    <p className="text-xs text-muted-foreground/80 dark:text-zinc-500 group-hover:text-muted-foreground line-clamp-3">
                        {folder.description || 'No description'}
                    </p>
                </div>
            </div>
            {/* Drop indicator overlay */}
            {isOver && (
                <div className="absolute inset-0 bg-gradient-to-r from-blue-500/10 to-blue-600/10 rounded-lg pointer-events-none animate-pulse" />
            )}
        </Card>
    );
};

interface WorkflowCardProps {
    workflow: WorkflowApp;
    isMultiSelected?: boolean;
    isBeingDragged?: boolean;
    onClick: (e: React.MouseEvent) => void;
    onSettings: (workflow: WorkflowApp) => void;
    onShare: (workflow: WorkflowApp) => void;
    onFork: (workflow: WorkflowApp) => void;
    sourceFolderId?: string | null;
    isMobile?: boolean;
}

export const WorkflowCard = ({
    workflow,
    isMultiSelected,
    isBeingDragged,
    onClick,
    onSettings,
    onShare,
    onFork,
    sourceFolderId,
    isMobile,
}: WorkflowCardProps) => {
    // Not-owned (shared) flows are read-only here: they can be opened and forked,
    // but moving/sharing/renaming them would be rejected server-side, so those
    // affordances are gated off (shown only in "Owned by anyone").
    const canManage = workflow.is_owner !== false;
    const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
        id: `workflow-grid-${workflow.id}`, // Unique ID for grid source to prevent sidebar from showing drag state
        disabled: isMobile || !canManage,
        data: {
            type: 'workflow',
            workflowId: workflow.id,
            workflowName: workflow.name,
            sourceFolderId,
            source: 'grid',
        },
    });
    const handledByPointerUpRef = useRef(false);

    // When the flow isn't ours, the leading pill shows the owner's name, so the
    // adornment should read as a person rather than a workflow graph icon.
    const isSharedFlow = workflow.is_owner === false && !!workflow.owner_name;

    return (
        <Card
            ref={setNodeRef}
            {...attributes}
            {...listeners}
            data-workflow-card
            className={cn(
                'bg-card shadow-sm hover:shadow-md dark:shadow-none dark:hover:shadow-none dark:bg-card/50 backdrop-blur-sm border-border/70 dark:border-border/50 dark:hover:bg-card/60 transition-all cursor-pointer group',
                'relative overflow-hidden h-[17.5rem]',
                (isDragging || isBeingDragged) && 'opacity-30 scale-95',
                isMultiSelected && 'ring-2 ring-blue-500/70'
            )}
            onClick={(e) => {
                if (handledByPointerUpRef.current) {
                    handledByPointerUpRef.current = false;
                    e.stopPropagation(); // Prevent click-outside handler from clearing selection
                    return;
                }
                onClick(e);
            }}
            onPointerUp={(e) => {
                // Handle multi-select on pointerUp to ensure modifier keys are captured
                // even when dnd-kit's pointer sensor intercepts events
                if (e.metaKey || e.ctrlKey || e.shiftKey) {
                    handledByPointerUpRef.current = true;
                    onClick(e as unknown as React.MouseEvent);
                }
            }}
        >
            {/* Image Preview Section — schematic of the real graph when the list
                entry carries a graph blob (zero-node workflows deliberately render
                as a blank canvas); CarbonGradient only for blob-less entries
                (shared-with-me listings). */}
            <div className="h-[11.25rem] relative overflow-hidden">
                {workflow.graph_preview ? (
                    // The graph preview themes itself (light mini-canvas in light
                    // mode), so it must NOT get the carbon wash below — that muddied
                    // the schematic.
                    <WorkflowGraphPreview
                        graph={workflow.graph_preview}
                        nodeIcons={getNodeIconData()}
                        className="w-full h-full"
                    />
                ) : (
                    <>
                        <CarbonGradient
                            identifier={workflow.id || workflow.name}
                            width={320}
                            height={180}
                            className="w-full h-full object-cover"
                        />
                        {/* Light-mode wash — the carbon texture is a dark asset, so
                            lighten it to a light surface in light mode while keeping
                            faint grain. Dark keeps the raw texture (pixel-identical). */}
                        <div className="absolute inset-0 pointer-events-none bg-muted/85 dark:bg-transparent" />
                    </>
                )}

                {/* Top bar — integration logos (left) and action buttons (right)
                    live in ONE flex row so they can never overlap on a narrow card
                    (both sidebars open / small screen): the logos pill yields
                    (min-w-0, clips under its rounded edge) while the buttons stay
                    fixed (shrink-0, ml-auto). Mirrors the bottom metadata bar. */}
                <div className="absolute top-2 inset-x-2 z-10 flex items-start gap-2">
                    {workflow.node_types?.some(isWorkflowIconType) && (
                        <div className="flex items-center px-2 py-1 rounded-full bg-card/80 border border-border dark:bg-black/60 dark:border-0 backdrop-blur-sm min-w-0 overflow-hidden">
                            <NodeIconStack
                                nodeTypes={workflowIconTypes(workflow)}
                                size="sm"
                                maxShown={4}
                                bare
                                filter={isWorkflowIconType}
                            />
                        </div>
                    )}
                    <div className="flex items-center gap-1.5 shrink-0 ml-auto">
                        {/* Fork button - shown for all workflows (useful for creating independent copies) */}
                        <button
                            onClick={(e) => {
                                e.stopPropagation();
                                onFork(workflow);
                            }}
                            className="p-2 rounded-full bg-card/80 border border-border dark:bg-black/60 dark:border-0 backdrop-blur-sm hover:bg-accent dark:hover:bg-zinc-700 transition-colors group/button min-w-9 min-h-9 flex items-center justify-center"
                            title="Fork (create a copy)"
                        >
                            <GitFork className="w-4 h-4 text-muted-foreground dark:text-foreground/80 group-hover/button:text-foreground transition-colors" />
                        </button>
                        {canManage && (
                            <button
                                onClick={(e) => {
                                    e.stopPropagation();
                                    onShare(workflow);
                                }}
                                className="p-2 rounded-full bg-card/80 border border-border dark:bg-black/60 dark:border-0 backdrop-blur-sm hover:bg-accent dark:hover:bg-zinc-700 transition-colors group/button min-w-9 min-h-9 flex items-center justify-center"
                                title="Share"
                            >
                                <Share2 className="w-4 h-4 text-muted-foreground dark:text-foreground/80 group-hover/button:text-foreground transition-colors" />
                            </button>
                        )}
                        <button
                            onClick={(e) => {
                                e.stopPropagation();
                                onSettings(workflow);
                            }}
                            className="p-2 rounded-full bg-card/80 border border-border dark:bg-black/60 dark:border-0 backdrop-blur-sm hover:bg-accent dark:hover:bg-zinc-700 transition-colors group/button min-w-9 min-h-9 flex items-center justify-center"
                            title="Settings"
                        >
                            <Settings className="w-4 h-4 text-muted-foreground dark:text-foreground/80 group-hover/button:text-foreground transition-colors" />
                        </button>
                    </div>
                </div>

                {/* Bottom overlay bar — one full-width flex row so the metadata pills
                    (leading owner/node-count pill + last-edited pill) and the permission
                    badge share horizontal space instead of overlapping on narrow cards.
                    The leading pill truncates first; the time pill and badge stay intact.
                    The metadata group carries a single tooltip with the full breakdown. */}
                <div className="absolute bottom-2 inset-x-2 z-10 flex items-center gap-1.5">
                    <div
                        className="flex items-center gap-1.5 min-w-0"
                        title={formatWorkflowMetaTooltip(workflow)}
                    >
                        <div className="flex items-center gap-1.5 px-2 py-1 rounded-full bg-card/80 border border-border dark:bg-black/60 dark:border-0 backdrop-blur-sm min-w-0">
                            {isSharedFlow ? (
                                <User className="w-3.5 h-3.5 shrink-0 text-sky-600 dark:text-sky-400" />
                            ) : (
                                <Workflow className="w-3.5 h-3.5 shrink-0 text-orange-600 dark:text-orange-400" />
                            )}
                            <span className="text-[0.625rem] text-foreground/80 truncate">
                                {formatWorkflowLeadingPill(workflow)}
                            </span>
                        </div>
                        {relativeShort(workflow.updated_at) && (
                            <div className="flex items-center gap-1 px-2 py-1 rounded-full bg-card/80 border border-border dark:bg-black/60 dark:border-0 backdrop-blur-sm shrink-0">
                                <Clock className="w-3 h-3 shrink-0 text-muted-foreground" />
                                <span className="text-[0.625rem] text-foreground/80 whitespace-nowrap">
                                    {relativeShort(workflow.updated_at)}
                                </span>
                            </div>
                        )}
                    </div>

                    {/* Permission badge - pinned to the right edge of the bar */}
                    {workflow.is_owner === false &&
                        workflow.user_permission && (
                            <span
                                className={cn(
                                    'ml-auto shrink-0 text-[0.625rem] px-2 py-1 rounded-full backdrop-blur-sm',
                                    workflow.user_permission === 'edit'
                                        ? 'bg-blue-600/40 text-blue-700 dark:text-blue-300'
                                        : 'bg-card/80 border border-border text-muted-foreground dark:bg-black/60 dark:border-0'
                                )}
                            >
                                {workflow.user_permission === 'edit'
                                    ? 'Can edit'
                                    : 'View only'}
                            </span>
                        )}
                </div>
            </div>

            {/* Content Section */}
            <div className="h-[6.25rem] p-4">
                <div className="space-y-1">
                    <h3 className="text-sm font-medium text-foreground/80 group-hover:text-foreground line-clamp-1 break-all">
                        {workflow.name}
                    </h3>
                    <p className="text-xs text-muted-foreground/80 dark:text-zinc-500 group-hover:text-muted-foreground line-clamp-3">
                        {workflow.description}
                    </p>
                </div>
            </div>
        </Card>
    );
};
