import { useCallback, useRef, type ComponentPropsWithRef, type CSSProperties, type ReactNode } from 'react';
import { Card } from '@/ui/card';
import {
    Clock,
    Folder,
    GitFork,
    Settings,
    Share2,
    User,
    Workflow,
    type LucideIcon,
} from 'lucide-react';
import { useDraggable } from '@dnd-kit/core';
import { CarbonGradient } from '@/ui/CarbonGradient';
import { WorkflowGraphPreview } from '@/ui/WorkflowGraphPreview';
import {
    workflowIconTypes,
    isWorkflowIconType,
} from '@/screens/workflows/browser/workflowBrowserStore';
import { cn } from '@/ui/utils';
import { useDroppableFolder } from '@/screens/workflows/browser/useDroppableFolder';
import { NodeIconStack } from '@/ui/NodeIconStack';
import { useNodeIconData } from '@/lib/nodeIconRegistry';
import { relativeShort } from '@/lib/formatters';
import { useAutomationBudget } from '@/screens/workflows/browser/automationBudget';
import type {
    WorkflowApp,
    FolderInfoLocal,
} from '@/screens/workflows/browser/useWorkflowBrowserData';

type FolderInfo = FolderInfoLocal;

// The card pill's and list rows' time, as every "+" list says it.
export { relativeShort };

// Leading text for the workflow pill — owner name when shared, otherwise
// the node count. Owner is load-bearing context so it takes priority on
// shared cards; node count lands in the time pill's tooltip in that case.
export function formatWorkflowLeadingPill(w: WorkflowApp): string {
    if (w.is_owner === false && w.owner_name) return w.owner_name;
    if (typeof w.node_count !== 'number') return 'Automation';
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
                {onShare && canManage && <CardAction label="Share" icon={Share2} onClick={() => onShare(folder.id)} />}
                {onSettings && <CardAction label="Settings" icon={Settings} onClick={() => onSettings(folder.id)} />}
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
                            {folder.workflow_count} automation
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

/** The grid the Automations page lays its cards in, and a space its automations: four columns at most, fewer as the
 *  grid itself narrows (both sidebars open, a small screen), never a card under 16rem. */
export function AutomationGrid({ className, style, ...grid }: ComponentPropsWithRef<'div'>) {
    // minmax() measures the grid's own width, so it follows the room it's given, not the viewport's breakpoints;
    // (100% - 3 gaps) / 4 keeps the cap at 4.
    const columns: CSSProperties = { gridTemplateColumns: 'repeat(auto-fill, minmax(max(16rem, calc((100% - 3 * var(--gap)) / 4)), 1fr))' };
    return <div className={cn('grid gap-[var(--gap)] [--gap:0.75rem] sm:[--gap:1rem]', className)} style={{ ...columns, ...style }} {...grid} />;
}

const CARD_ACTION =
    'p-2 rounded-full bg-card/80 border border-border dark:bg-black/60 dark:border-0 backdrop-blur-sm hover:bg-accent dark:hover:bg-zinc-700 transition-colors group/button min-w-9 min-h-9 flex items-center justify-center';

/** One of the round actions over a card's picture: its click is its own, never the card's. */
export function CardAction({ label, icon: Icon, onClick }: { label: string; icon: LucideIcon; onClick: () => void }) {
    return (
        <button
            type="button"
            onClick={(e) => {
                e.stopPropagation();
                onClick();
            }}
            className={CARD_ACTION}
            title={label}
            aria-label={label}
        >
            <Icon className="w-4 h-4 text-muted-foreground dark:text-foreground/80 group-hover/button:text-foreground transition-colors" />
        </button>
    );
}

/** A card's action that opens a menu (a space's ⋯), drawn as its buttons are. */
export const CARD_ACTION_TRIGGER = cn(CARD_ACTION, 'h-9 w-9 text-muted-foreground dark:text-foreground/80 hover:text-foreground');

/** A fact on a card's picture: its mark, then a few words that give way first on a narrow card. */
export function CardPill({ icon, children, className }: { icon?: ReactNode; children: ReactNode; className?: string }) {
    return (
        <div className={cn('flex items-center gap-1.5 px-2 py-1 rounded-full bg-card/80 border border-border dark:bg-black/60 dark:border-0 backdrop-blur-sm min-w-0', className)}>
            {icon}
            <span className="text-[0.625rem] text-foreground/80 truncate">{children}</span>
        </div>
    );
}

/** The badge at the right of a card's facts: what the reader holds of it (`strong`: they can change it). */
export function CardBadge({ children, strong, title }: { children: ReactNode; strong?: boolean; title?: string }) {
    return (
        <span
            title={title}
            className={cn(
                'ml-auto shrink-0 text-[0.625rem] px-2 py-1 rounded-full backdrop-blur-sm',
                strong ? 'bg-blue-600/40 text-blue-700 dark:text-blue-300' : 'bg-card/80 border border-border text-muted-foreground dark:bg-black/60 dark:border-0'
            )}
        >
            {children}
        </span>
    );
}

/** What a card draws of an automation. */
export type CardAutomation = Pick<WorkflowApp, 'id' | 'name' | 'description' | 'graph_preview' | 'node_types'>;

/** An automation as a card: a picture of its graph (a texture where its listing carries none), the apps it uses and
 *  its `actions` along the top, its `facts` and a `badge` along the bottom, then its name and description. The
 *  Automations page draws it with its folders' drag and selection (WorkflowCard), a space with what it shares. */
export function AutomationCard({
    automation,
    actions,
    facts,
    factsTitle,
    badge,
    className,
    ...card
}: {
    automation: CardAutomation;
    actions?: ReactNode;
    facts?: ReactNode;
    /** The facts' tooltip: the whole of what they shorten. */
    factsTitle?: string;
    badge?: ReactNode;
} & ComponentPropsWithRef<'div'>) {
    // The icon map can land after the cards draw (a client navigation into the dashboard): they draw again with it.
    const nodeIcons = useNodeIconData();
    return (
        <Card
            className={cn(
                'bg-card shadow-sm hover:shadow-md dark:shadow-none dark:hover:shadow-none dark:bg-card/50 backdrop-blur-sm border-border/70 dark:border-border/50 dark:hover:bg-card/60 transition-all cursor-pointer group',
                'relative overflow-hidden h-[17.5rem]',
                className
            )}
            {...card}
        >
            {/* A schematic of the real graph where the listing carries one (an empty graph draws as a blank canvas);
                the texture only where it carries none (shared-with-me listings, what a space shares through agents). */}
            <div className="h-[11.25rem] relative overflow-hidden">
                {automation.graph_preview ? (
                    // The graph preview themes itself (a light mini-canvas in light mode), so it gets no wash: that
                    // muddied the schematic.
                    <WorkflowGraphPreview graph={automation.graph_preview} nodeIcons={nodeIcons} className="w-full h-full" />
                ) : (
                    <>
                        <CarbonGradient identifier={automation.id || automation.name} width={320} height={180} className="w-full h-full object-cover" />
                        {/* The carbon texture is a dark asset: light mode lightens it to a light surface, keeping faint
                            grain. Dark keeps the raw texture. */}
                        <div className="absolute inset-0 pointer-events-none bg-muted/85 dark:bg-transparent" />
                    </>
                )}

                {/* Its apps (left) and its actions (right) share one row, so they never overlap on a narrow card: the
                    apps give way (they clip under their pill's edge) while the actions keep their size. */}
                <div className="absolute top-2 inset-x-2 z-10 flex items-start gap-2">
                    {automation.node_types?.some(isWorkflowIconType) && (
                        <div className="flex items-center px-2 py-1 rounded-full bg-card/80 border border-border dark:bg-black/60 dark:border-0 backdrop-blur-sm min-w-0 overflow-hidden">
                            <NodeIconStack nodeTypes={workflowIconTypes(automation)} size="sm" maxShown={4} bare filter={isWorkflowIconType} />
                        </div>
                    )}
                    {actions && <div className="flex items-center gap-1.5 shrink-0 ml-auto">{actions}</div>}
                </div>

                {/* Its facts and its badge share one row too: the first fact gives way first, the badge keeps its size
                    at the right edge. */}
                <div className="absolute bottom-2 inset-x-2 z-10 flex items-center gap-1.5">
                    <div className="flex items-center gap-1.5 min-w-0" title={factsTitle}>
                        {facts}
                    </div>
                    {badge}
                </div>
            </div>

            <div className="h-[6.25rem] p-4">
                <div className="space-y-1">
                    <h3 className="text-sm font-medium text-foreground/80 group-hover:text-foreground line-clamp-1 break-all">{automation.name}</h3>
                    <p className="text-xs text-muted-foreground/80 dark:text-zinc-500 group-hover:text-muted-foreground line-clamp-3">{automation.description}</p>
                </div>
            </div>
        </Card>
    );
}

interface WorkflowCardProps {
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
}

/** The Automations page's card: dragged into folders, picked with a modifier, forked, shared and set from its actions. */
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
    // An agent's automation leads with its month's spend against its budget instead.
    const budgeted = useAutomationBudget(workflow.id);
    const edited = relativeShort(workflow.updated_at);

    return (
        <AutomationCard
            ref={setNodeRef}
            {...attributes}
            {...listeners}
            data-workflow-card
            automation={workflow}
            className={cn((isDragging || isBeingDragged) && 'opacity-30 scale-95', isMultiSelected && 'ring-2 ring-blue-500/70')}
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
            actions={
                <>
                    {/* Fork: every automation, an independent copy */}
                    <CardAction label="Fork (create a copy)" icon={GitFork} onClick={() => onFork(workflow)} />
                    {onShare && canManage && <CardAction label="Share" icon={Share2} onClick={() => onShare(workflow)} />}
                    <CardAction label="Settings" icon={Settings} onClick={() => onSettings(workflow)} />
                </>
            }
            factsTitle={formatWorkflowMetaTooltip(workflow)}
            facts={
                <>
                    {budgeted && canManage ? (
                        <budgeted.Pill budget={budgeted.budget} variant="card" />
                    ) : (
                        <CardPill
                            icon={
                                isSharedFlow ? (
                                    <User className="w-3.5 h-3.5 shrink-0 text-sky-600 dark:text-sky-400" />
                                ) : (
                                    <Workflow className="w-3.5 h-3.5 shrink-0 text-orange-600 dark:text-orange-400" />
                                )
                            }
                        >
                            {formatWorkflowLeadingPill(workflow)}
                        </CardPill>
                    )}
                    {edited && (
                        <CardPill icon={<Clock className="w-3 h-3 shrink-0 text-muted-foreground" />} className="shrink-0">
                            {edited}
                        </CardPill>
                    )}
                </>
            }
            badge={
                workflow.is_owner === false &&
                workflow.user_permission && (
                    <CardBadge strong={workflow.user_permission === 'edit'}>{workflow.user_permission === 'edit' ? 'Can edit' : 'View only'}</CardBadge>
                )
            }
        />
    );
};
