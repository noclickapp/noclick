// Compact single-line list rows for the WorkflowBrowser — an alternative layout
// to the card grid (WorkflowBrowserCards), toggled via the header grid/list
// control. FolderRow/WorkflowRow mirror the dnd-kit drag/drop, multi-select, and
// action-handler wiring of FolderCard/WorkflowCard so both layouts behave
// identically; only the visual presentation differs. Drag uses source 'list',
// which the drag hook treats like 'grid' for multi-select but the drag overlay
// renders as a compact pill (a 280px card preview would be absurd for a row).

import { useCallback, useRef } from 'react';
import {
    Clock,
    CornerDownRight,
    Folder,
    GitFork,
    Settings,
    Share2,
    Workflow,
} from 'lucide-react';
import { useDraggable } from '@dnd-kit/core';
import { Card } from '~/components/ui/card';
import { cn } from '~/lib/utils';
import { useDroppableFolder } from '~/hooks/useDroppableFolder';
import type {
    WorkflowApp,
    FolderInfoLocal,
} from '~/hooks/useWorkflowBrowserData';
import { NodeIconStack } from '~/components/shared/NodeIconStack';
import {
    workflowIconTypes,
    isWorkflowIconType,
} from '~/lib/workflowBrowserStore';
import {
    relativeShort,
    formatWorkflowLeadingPill,
    formatWorkflowMetaTooltip,
} from './WorkflowBrowserCards';

type FolderInfo = FolderInfoLocal;

// Integration logos a workflow row shows are rendered via the shared
// NodeIconStack (see <NodeIconStack> usage in WorkflowRow below), filtered to
// branded integrations + the agent (bare control-flow utilities only have
// generic icons).

// Subtle "in <folder>" chip shown on global-search results so users can tell
// where a nested item lives.
function LocationChip({ location }: { location?: string }) {
    if (!location) return null;
    return (
        <span
            title={`in ${location}`}
            className="hidden lg:inline-flex items-center gap-1 shrink-0 max-w-[10rem] truncate text-[0.6875rem] text-muted-foreground/60 dark:text-white/30"
        >
            <CornerDownRight className="w-3 h-3 shrink-0" />
            <span className="truncate">{location}</span>
        </span>
    );
}

// Shared base classes for a row. Matches the Settings list rows (API keys,
// resource lists): white/[0.03] surface, rounded-xl, subtle hover lift.
const ROW_BASE =
    'group relative flex items-center gap-4 px-4 py-3 rounded-xl border shadow-none bg-card dark:bg-foreground/[0.03] border-border/50 dark:border-white/[0.06] hover:bg-muted dark:hover:bg-foreground/[0.05] hover:border-border dark:hover:border-white/[0.10] transition-colors cursor-pointer select-none';

// Inline action button (fork/share/settings) styled like the Settings row icon
// buttons — faded by default, brightening on hover.
function RowAction({
    icon: Icon,
    title,
    onClick,
}: {
    icon: typeof Settings;
    title: string;
    onClick: () => void;
}) {
    return (
        <button
            type="button"
            title={title}
            onClick={(e) => {
                e.stopPropagation();
                onClick();
            }}
            className="p-2 rounded-lg text-muted-foreground/60 dark:text-white/30 hover:text-foreground/80 hover:bg-foreground/[0.05] transition-colors flex items-center justify-center"
        >
            <Icon className="w-4 h-4" />
        </button>
    );
}

interface FolderRowProps {
    folder: FolderInfo;
    onClick: (e: React.MouseEvent) => void;
    onSettings?: (folderId: string) => void;
    onShare?: (folderId: string) => void;
    isMultiSelected?: boolean;
    isBeingDragged?: boolean;
    sourceFolderId?: string | null;
    isMobile?: boolean;
    /** Disables drag (e.g. during global search, where the source folder is ambiguous). */
    dragDisabled?: boolean;
    /** Parent location shown as a chip on global-search results. */
    location?: string;
    /** Keyboard-nav highlight (search results). */
    isHighlighted?: boolean;
}

export const FolderRow = ({
    folder,
    onClick,
    onSettings,
    onShare,
    isMultiSelected,
    isBeingDragged,
    sourceFolderId,
    isMobile,
    dragDisabled,
    location,
    isHighlighted,
}: FolderRowProps) => {
    // Shared (not-owned) folders are read-only: move/share would be rejected
    // server-side, so those affordances are gated off.
    const canManage = folder.is_owner !== false;
    const { isOver, setNodeRef: setDropRef } = useDroppableFolder({
        folderId: folder.id,
        idSuffix: 'row',
        targetFolderPath: folder.path,
    });
    const {
        attributes,
        listeners,
        setNodeRef: setDragRef,
        isDragging,
    } = useDraggable({
        id: `folder-drag-list-${folder.id}`,
        disabled: isMobile || dragDisabled || !canManage,
        data: {
            type: 'folder',
            folderId: folder.id,
            folderName: folder.name,
            parentFolderId: sourceFolderId,
            folderPath: folder.path,
            source: 'list',
        },
    });

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
            onClick={onClick}
            className={cn(
                ROW_BASE,
                isHighlighted &&
                    'bg-foreground/[0.07] border-muted-foreground/30 dark:border-white/[0.16]',
                isOver &&
                    'bg-blue-600/20 border-blue-400/60 ring-1 ring-blue-500/30',
                (isDragging || isBeingDragged) && 'opacity-30',
                isMultiSelected && 'ring-2 ring-blue-500/70 border-blue-500/40'
            )}
        >
            <Folder className="w-4 h-4 shrink-0 text-yellow-600/80" />
            <span className="flex-1 min-w-0 truncate text-sm font-medium text-foreground">
                {folder.name}
            </span>
            <LocationChip location={location} />
            {folder.is_owner === false && folder.owner_name && (
                <span className="shrink-0 text-xs text-muted-foreground/70 dark:text-white/40 max-w-[10rem] truncate">
                    {folder.owner_name}
                </span>
            )}
            <span className="shrink-0 text-xs text-muted-foreground/70 dark:text-white/40 tabular-nums">
                {folder.workflow_count} workflow
                {folder.workflow_count !== 1 ? 's' : ''}
            </span>
            <div className="flex items-center gap-0.5 shrink-0">
                {onShare && canManage && (
                    <RowAction
                        icon={Share2}
                        title="Share"
                        onClick={() => onShare(folder.id)}
                    />
                )}
                {onSettings && (
                    <RowAction
                        icon={Settings}
                        title="Settings"
                        onClick={() => onSettings(folder.id)}
                    />
                )}
            </div>
        </Card>
    );
};

interface WorkflowRowProps {
    workflow: WorkflowApp;
    isMultiSelected?: boolean;
    isBeingDragged?: boolean;
    onClick: (e: React.MouseEvent) => void;
    onSettings: (workflow: WorkflowApp) => void;
    onShare: (workflow: WorkflowApp) => void;
    onFork: (workflow: WorkflowApp) => void;
    sourceFolderId?: string | null;
    isMobile?: boolean;
    /** Disables drag (e.g. during global search, where the source folder is ambiguous). */
    dragDisabled?: boolean;
    /** Parent location shown as a chip on global-search results. */
    location?: string;
    /** Keyboard-nav highlight (search results). */
    isHighlighted?: boolean;
}

export const WorkflowRow = ({
    workflow,
    isMultiSelected,
    isBeingDragged,
    onClick,
    onSettings,
    onShare,
    onFork,
    sourceFolderId,
    isMobile,
    dragDisabled,
    location,
    isHighlighted,
}: WorkflowRowProps) => {
    // Not-owned (shared) flows are read-only: moving/sharing would be rejected
    // server-side, so drag + the Share action are gated off.
    const canManage = workflow.is_owner !== false;
    const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
        id: `workflow-list-${workflow.id}`,
        disabled: isMobile || dragDisabled || !canManage,
        data: {
            type: 'workflow',
            workflowId: workflow.id,
            workflowName: workflow.name,
            sourceFolderId,
            source: 'list',
        },
    });
    // Capture multi-select on pointerUp so modifier keys register even when the
    // dnd pointer sensor intercepts the event — same approach as WorkflowCard.
    const handledByPointerUpRef = useRef(false);

    const editTime = relativeShort(workflow.updated_at);
    const isShared = workflow.is_owner === false;

    return (
        <Card
            ref={setNodeRef}
            {...attributes}
            {...listeners}
            data-workflow-card
            onClick={(e) => {
                if (handledByPointerUpRef.current) {
                    handledByPointerUpRef.current = false;
                    e.stopPropagation();
                    return;
                }
                onClick(e);
            }}
            onPointerUp={(e) => {
                if (e.metaKey || e.ctrlKey || e.shiftKey) {
                    handledByPointerUpRef.current = true;
                    onClick(e as unknown as React.MouseEvent);
                }
            }}
            className={cn(
                ROW_BASE,
                isHighlighted &&
                    'bg-foreground/[0.07] border-muted-foreground/30 dark:border-white/[0.16]',
                (isDragging || isBeingDragged) && 'opacity-30',
                isMultiSelected && 'ring-2 ring-blue-500/70 border-blue-500/40'
            )}
        >
            <Workflow className="w-4 h-4 shrink-0 text-orange-600 dark:text-orange-400" />
            <span className="flex-1 min-w-0 truncate text-sm font-medium text-foreground">
                {workflow.name}
            </span>
            <LocationChip location={location} />
            {/* Owner attribution for shared rows. The desktop metadata span below
                carries it via the leading pill but is hidden on mobile, so surface
                it here on small screens to match the card (which always shows it). */}
            {isShared && workflow.owner_name && (
                <span className="sm:hidden shrink-0 text-xs text-foreground/40 max-w-[8rem] truncate">
                    {workflow.owner_name}
                </span>
            )}
            <NodeIconStack
                nodeTypes={workflowIconTypes(workflow)}
                size="sm"
                maxShown={4}
                filter={isWorkflowIconType}
                className="hidden md:flex shrink-0"
            />
            <span
                className="hidden sm:flex items-center gap-1.5 shrink-0 text-xs text-muted-foreground/70 dark:text-white/40"
                title={formatWorkflowMetaTooltip(workflow)}
            >
                <span className="max-w-[10rem] truncate">
                    {formatWorkflowLeadingPill(workflow)}
                </span>
                {editTime && (
                    <>
                        <Clock className="w-3 h-3 text-muted-foreground/60 dark:text-white/30" />
                        <span className="tabular-nums">{editTime}</span>
                    </>
                )}
            </span>
            {isShared && workflow.user_permission && (
                <span
                    className={cn(
                        'shrink-0 text-[0.625rem] px-1.5 py-0.5 rounded border',
                        workflow.user_permission === 'edit'
                            ? 'bg-indigo-500/10 text-indigo-600 dark:text-indigo-300 border-indigo-500/30'
                            : 'bg-foreground/[0.04] text-muted-foreground/70 dark:text-white/40 border-border/50 dark:border-white/[0.06]'
                    )}
                >
                    {workflow.user_permission === 'edit'
                        ? 'Can edit'
                        : 'View only'}
                </span>
            )}
            <div className="flex items-center gap-0.5 shrink-0">
                <RowAction
                    icon={GitFork}
                    title="Fork (create a copy)"
                    onClick={() => onFork(workflow)}
                />
                {canManage && (
                    <RowAction
                        icon={Share2}
                        title="Share"
                        onClick={() => onShare(workflow)}
                    />
                )}
                <RowAction
                    icon={Settings}
                    title="Settings"
                    onClick={() => onSettings(workflow)}
                />
            </div>
        </Card>
    );
};
