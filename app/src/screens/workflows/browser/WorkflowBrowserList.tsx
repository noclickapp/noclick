// Compact single-line list rows for the WorkflowBrowser — an alternative layout
// to the card grid (WorkflowBrowserCards), toggled via the header grid/list
// control. FolderRow/WorkflowRow mirror the dnd-kit drag/drop, multi-select, and
// action-handler wiring of FolderCard/WorkflowCard so both layouts behave
// identically; only the visual presentation differs. Drag uses source 'list',
// which the drag hook treats like 'grid' for multi-select but the drag overlay
// renders as a compact pill (a 280px card preview would be absurd for a row).
// An automation's row itself (AutomationRow) is drawn by a space's Automations too.

import { Fragment, useCallback, useRef, type ComponentPropsWithRef, type ReactNode } from 'react';
import { CornerDownRight, Folder, GitFork, MoreHorizontal, Settings, Share2, Workflow } from 'lucide-react';
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from '@/ui/dropdown-menu';
import { useDraggable } from '@dnd-kit/core';
import { cn } from '@/ui/utils';
import { useDroppableFolder } from '@/screens/workflows/browser/useDroppableFolder';
import type {
    WorkflowApp,
    FolderInfoLocal,
} from '@/screens/workflows/browser/useWorkflowBrowserData';
import { NodeIconStack } from '@/ui/NodeIconStack';
import {
    workflowIconTypes,
    isWorkflowIconType,
} from '@/screens/workflows/browser/workflowBrowserStore';
import {
    relativeShort,
    formatWorkflowLeadingPill,
    formatWorkflowMetaTooltip,
} from '@/screens/workflows/browser/WorkflowBrowserCards';
import { useAutomationBudget } from '@/screens/workflows/browser/automationBudget';

type FolderInfo = FolderInfoLocal;

// Subtle "in <folder>" chip shown on global-search results so users can tell
// where a nested item lives.
function LocationChip({ location }: { location?: string }) {
    if (!location) return null;
    return (
        <span title={`in ${location}`} className="hidden max-w-[10rem] shrink-0 items-center gap-1 truncate text-[12px] text-muted-foreground lg:inline-flex">
            <CornerDownRight className="h-3 w-3 shrink-0" />
            <span className="truncate">{location}</span>
        </span>
    );
}

/** The hairline list the rows sit in, one edge around them all. */
export function RowList({ children }: { children: ReactNode }) {
    return (
        <div className="divide-y divide-border overflow-hidden rounded-2xl border border-border bg-card dark:divide-foreground/[0.06] dark:border-foreground/[0.08] dark:bg-foreground/[0.02]">
            {children}
        </div>
    );
}

// One row: a quiet tile, the name, its facts, and its actions on hover.
const ROW_BASE = 'group relative flex cursor-pointer select-none items-center gap-3 px-4 py-2.5 transition-colors hover:bg-foreground/[0.03]';
const ROW_HIGHLIGHT = 'bg-foreground/[0.06] hover:bg-foreground/[0.06]';
const ROW_SELECTED = 'bg-foreground/[0.07] shadow-[inset_0_0_0_2px_hsl(var(--foreground)/0.45)]';

interface RowAction {
    label: string;
    icon: typeof Share2;
    onSelect: () => void;
}

const ROW_ACTION =
    'grid h-8 w-8 place-items-center rounded-lg text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground';

/** A row's actions: revealed on hover on a laptop, one menu on a phone. */
function RowActions({ actions, isMobile }: { actions: RowAction[]; isMobile?: boolean }) {
    if (!actions.length) return null;
    if (isMobile) {
        return (
            <DropdownMenu>
                <DropdownMenuTrigger asChild>
                    <button type="button" aria-label="Actions" className={ROW_ACTION} onClick={(e) => e.stopPropagation()}>
                        <MoreHorizontal className="h-4 w-4" />
                    </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="min-w-[180px] rounded-xl p-1" onClick={(e) => e.stopPropagation()}>
                    {actions.map(({ label, icon: Icon, onSelect }) => (
                        <DropdownMenuItem key={label} onSelect={onSelect} className="gap-2.5 rounded-lg px-2.5 py-2 text-[14px]">
                            <Icon className="h-4 w-4 text-muted-foreground" />
                            {label}
                        </DropdownMenuItem>
                    ))}
                </DropdownMenuContent>
            </DropdownMenu>
        );
    }
    return (
        <div className="flex items-center gap-1.5 opacity-0 transition-opacity duration-150 focus-within:opacity-100 group-hover:opacity-100">
            {actions.map(({ label, icon: Icon, onSelect }) => (
                <button
                    key={label}
                    type="button"
                    title={label}
                    aria-label={label}
                    className={ROW_ACTION}
                    onClick={(e) => {
                        e.stopPropagation();
                        onSelect();
                    }}
                >
                    <Icon className="h-4 w-4" />
                </button>
            ))}
        </div>
    );
}

/** Enter on a focused row opens it, as a click would. */
function openOnEnter(e: React.KeyboardEvent, open: (e: React.MouseEvent) => void) {
    if (e.key !== 'Enter' || e.target !== e.currentTarget) return;
    e.preventDefault();
    open(e as unknown as React.MouseEvent);
}

function RowTile({ children }: { children: ReactNode }) {
    return <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-foreground/[0.05] text-foreground/70">{children}</span>;
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

    const actions: RowAction[] = [];
    if (onShare && canManage) actions.push({ label: 'Share', icon: Share2, onSelect: () => onShare(folder.id) });
    if (onSettings) actions.push({ label: 'Settings', icon: Settings, onSelect: () => onSettings(folder.id) });
    const count = folder.workflow_count;

    return (
        <div
            ref={mergedRef}
            {...attributes}
            {...listeners}
            data-folder-card
            role="button"
            tabIndex={0}
            onClick={onClick}
            onKeyDown={(e) => openOnEnter(e, onClick)}
            className={cn(
                ROW_BASE,
                isHighlighted && ROW_HIGHLIGHT,
                isOver && 'bg-foreground/[0.06] shadow-[inset_0_0_0_1px_hsl(var(--foreground)/0.25)]',
                (isDragging || isBeingDragged) && 'opacity-30',
                isMultiSelected && ROW_SELECTED
            )}
        >
            <RowTile>
                <Folder className="h-4 w-4" strokeWidth={1.75} />
            </RowTile>
            <span className="min-w-0 flex-1 truncate text-[14px] font-medium text-foreground">{folder.name}</span>
            <LocationChip location={location} />
            {folder.is_owner === false && folder.owner_name && (
                <span className="max-w-[10rem] shrink-0 truncate text-[12.5px] text-muted-foreground">{folder.owner_name}</span>
            )}
            <span className="shrink-0 text-[12.5px] tabular-nums text-muted-foreground">
                {count === 0 ? 'Empty' : `${count} ${count === 1 ? 'automation' : 'automations'}`}
            </span>
            <RowActions actions={actions} isMobile={isMobile} />
        </div>
    );
};

/** The badge beside a row's facts: what the reader holds of it. */
export function RowBadge({ children, title }: { children: ReactNode; title?: string }) {
    return (
        <span title={title} className="shrink-0 rounded-full bg-foreground/[0.06] px-2 py-0.5 text-[11.5px] font-medium text-muted-foreground">
            {children}
        </span>
    );
}

/** What a row draws of an automation. */
export type RowAutomation = Pick<WorkflowApp, 'id' | 'name' | 'graph_preview' | 'node_types'>;

/** An automation as a row: its tile and name, where it lives (a search's), the apps it uses, its `facts` (under its
 *  name on a phone, beside it elsewhere), a `badge` and its `actions`. The Automations page draws it with its folders'
 *  drag and selection (WorkflowRow), a space with what it shares. */
export function AutomationRow({
    automation,
    facts,
    factsTitle,
    badge,
    actions,
    location,
    highlighted,
    className,
    ...row
}: {
    automation: RowAutomation;
    facts: ReactNode[];
    /** The facts' tooltip: the whole of what they shorten. */
    factsTitle?: string;
    badge?: ReactNode;
    actions?: ReactNode;
    /** Parent location shown as a chip on global-search results. */
    location?: string;
    /** Keyboard-nav highlight (search results). */
    highlighted?: boolean;
} & ComponentPropsWithRef<'div'>) {
    const shown = facts.filter((fact) => fact !== null && fact !== undefined && fact !== false && fact !== '');
    return (
        <div role="button" tabIndex={0} className={cn(ROW_BASE, highlighted && ROW_HIGHLIGHT, className)} {...row}>
            <RowTile>
                <Workflow className="h-4 w-4" strokeWidth={1.75} />
            </RowTile>
            <span className="min-w-0 flex-1">
                <span className="block truncate text-[14px] font-medium text-foreground">{automation.name}</span>
                {/* A phone has no room for the facts column: they sit under the name. */}
                <span className="block truncate text-[12.5px] text-muted-foreground sm:hidden">
                    {shown.map((fact, i) => (
                        <Fragment key={i}>
                            {i > 0 && ' · '}
                            {fact}
                        </Fragment>
                    ))}
                </span>
            </span>
            <LocationChip location={location} />
            <NodeIconStack nodeTypes={workflowIconTypes(automation)} size="sm" maxShown={4} filter={isWorkflowIconType} className="hidden shrink-0 md:flex" />
            <span className="hidden shrink-0 items-center gap-1.5 text-[12.5px] text-muted-foreground sm:flex" title={factsTitle}>
                {shown.map((fact, i) => (
                    <Fragment key={i}>
                        {i > 0 && <span aria-hidden>·</span>}
                        <span className={i === 0 ? 'max-w-[12rem] truncate' : 'tabular-nums'}>{fact}</span>
                    </Fragment>
                ))}
            </span>
            {badge}
            {actions}
        </div>
    );
}

interface WorkflowRowProps {
    workflow: WorkflowApp;
    isMultiSelected?: boolean;
    isBeingDragged?: boolean;
    onClick: (e: React.MouseEvent) => void;
    onSettings: (workflow: WorkflowApp) => void;
    /** Absent: nothing to share it with (no Share shows). */
    onShare?: (workflow: WorkflowApp) => void;
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
    // An agent's automation leads with its month's spend against its budget, as its card does.
    const budgeted = useAutomationBudget(workflow.id);
    const leading = budgeted && canManage ? <budgeted.Pill budget={budgeted.budget} variant="row" /> : formatWorkflowLeadingPill(workflow);
    const actions: RowAction[] = [{ label: 'Fork', icon: GitFork, onSelect: () => onFork(workflow) }];
    if (onShare && canManage) actions.push({ label: 'Share', icon: Share2, onSelect: () => onShare(workflow) });
    actions.push({ label: 'Settings', icon: Settings, onSelect: () => onSettings(workflow) });

    return (
        <AutomationRow
            ref={setNodeRef}
            {...attributes}
            {...listeners}
            data-workflow-card
            automation={workflow}
            location={location}
            highlighted={isHighlighted}
            onKeyDown={(e) => openOnEnter(e, onClick)}
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
            className={cn((isDragging || isBeingDragged) && 'opacity-30', isMultiSelected && ROW_SELECTED)}
            facts={[leading, editTime]}
            factsTitle={formatWorkflowMetaTooltip(workflow)}
            badge={isShared && workflow.user_permission && <RowBadge>{workflow.user_permission === 'edit' ? 'Can edit' : 'View only'}</RowBadge>}
            actions={<RowActions actions={actions} isMobile={isMobile} />}
        />
    );
};
