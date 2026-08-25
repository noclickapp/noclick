/**
 * Shared scaffold for the FlowCanvas Setup tab's Split Rail layout — restored
 * from the pre-2026-07-25 setupviews module (the schema-scanning wizard's
 * shell) and pruned to the rail + identity half: the step data model, node
 * badges, step kind/state marks, circular progress, and the collapsible +
 * resizable rail (expanded groups / collapsed icon strip). The field-editor
 * half was NOT restored — the state-derived Setup tab renders real product
 * surfaces (CredentialPhase / NodeConfig) in its right pane instead.
 */
import { useState, useCallback, useEffect } from 'react';
import {
    Bot,
    CheckCircle2,
    Circle,
    GitBranch,
    KeyRound,
    SlidersHorizontal,
    Braces,
    FlaskConical,
    Settings,
    PanelLeftOpen,
    Wrench,
    type LucideIcon,
} from 'lucide-react';
import { cn } from '~/lib/utils';
import { getNodeMetadata } from '~/components/workflow/nodes/nodeRegistry';
import { BrandIcon, type BrandIconComponent } from '~/components/shared/BrandIcon';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '~/components/ui/tooltip';

// ---------------------------------------------------------------------------
// Data model — mirrors the real SetupStep union in TypeformSetupView, enriched
// with mock fill state (`state`) and per-node grouping so both the one-field
// wizard variations and the scannable overview variations can share one fixture.
// ---------------------------------------------------------------------------

/** What a step asks the user to do — pick a node's operation, pick the tool
 *  operations exposed to an agent/MCP host, connect an account, or fill a
 *  required config field. Mirrors SetupStep['kind']. */
export type StepKind = 'operation' | 'tool' | 'credential' | 'config' | 'agent';

/** Mock fill state for the showcase. Real flow derives this from node data. */
export type StepState = 'done' | 'todo';

/** Editor surface to render for a `config` step. */
export type FieldKind = 'text' | 'textarea' | 'enum' | 'boolean' | 'number' | 'dynamic';

export interface SetupNodeMeta {
    nodeId: string;
    /** Real registry node type (e.g. 'automation-slack') so getNodeMetadata resolves the brand icon. */
    nodeType: string;
    /** Display label — a custom node label or the node-type label. */
    label: string;
    /** Optional one-line node goal, shown in context headers. */
    goal?: string;
    /** Upstream node ids feeding into this node (for "Inputs" chips). */
    upstream: string[];
}

export interface StepOption {
    value: string;
    label: string;
    description?: string;
    /** Operation-only: object category (x-category) for grouping in the picker. */
    category?: string;
    /** Operation-only: this operation starts the workflow on an external event. */
    isTrigger?: boolean;
    /** Operation-only: required API-tier label (x-tier-label), e.g. "⭐ Basic". */
    tierLabel?: string;
}

export interface SetupStep {
    id: string;
    nodeId: string;
    kind: StepKind;
    /** Step heading, e.g. "Choose an action", "Slack channel", "Connect Apollo". */
    title: string;
    description?: string;
    required: boolean;
    /** Mock fill state. */
    state: StepState;

    // kind: 'operation' | config enum — selectable options
    options?: StepOption[];

    // kind: 'config'
    fieldKind?: FieldKind;
    /** Config-only: the raw field key in the node's config schema. */
    fieldKey?: string;
    placeholder?: string;
    /** Current value for a filled step (string-encoded; bools as 'true'/'false'). */
    value?: string;

    // kind: 'credential'
    credentialType?: string;
    credentialLabel?: string;
    /** All credential types this slot accepts (e.g. ['slack_oauth', 'slack_bot']). */
    acceptedCredentialTypes?: string[];
    /** When connected (state === 'done'), a human label for the linked account. */
    connectedAccount?: string;
    /** Tool-only: whether the provider feeds an agent, an MCP server, or both. */
    consumerTypes?: Array<'agent' | 'mcp-server'>;

    /** Config-only: the raw JSON schema for the field. Carried so the real-data
     *  variation can drive the production field renderers (dynamic options,
     *  custom widgets) — the mock editors ignore it. */
    fieldSchema?: Record<string, unknown>;
}

export interface SetupSession {
    workflowName: string;
    /** Node metadata keyed by nodeId. */
    nodes: Record<string, SetupNodeMeta>;
    /** Steps in edge order (topologically sorted upstream of the workflow). */
    steps: SetupStep[];
}

// ---------------------------------------------------------------------------
// Design tokens — black base + white-opacity layers, with per-kind accents that
// echo the /logviews trigger palette (sky / violet / teal); done/todo status
// stays neutral ink — the rail never celebrates in colour.
// ---------------------------------------------------------------------------

export interface StepKindToken {
    label: string;
    Icon: LucideIcon;
    text: string; // text color class
    bg: string; // soft fill
    border: string; // hairline border
    dot: string; // solid dot bg
}

// One quiet treatment for every kind — the badge NAMES the step type, it
// doesn't color-code it. State carries the only hue: unfilled reads amber
// (STEP_STATE_META / StepStateMark), done reads neutral ink.
const NEUTRAL_KIND = {
    text: 'text-foreground/55',
    bg: 'bg-foreground/[0.05]',
    border: 'border-foreground/15',
    dot: 'bg-foreground/35',
};

export const STEP_KIND_META: Record<StepKind, StepKindToken> = {
    operation: { label: 'Action', Icon: GitBranch, ...NEUTRAL_KIND },
    tool: { label: 'Tools', Icon: Wrench, ...NEUTRAL_KIND },
    credential: { label: 'Credential', Icon: KeyRound, ...NEUTRAL_KIND },
    config: { label: 'Field', Icon: SlidersHorizontal, ...NEUTRAL_KIND },
    agent: { label: 'Agent', Icon: Bot, ...NEUTRAL_KIND },
};

export interface StepStateToken {
    label: string;
    text: string;
    dot: string;
    ring: string;
}

export const STEP_STATE_META: Record<StepState, StepStateToken> = {
    done: { label: 'Done', text: 'text-foreground/70', dot: 'bg-foreground/60', ring: 'border-foreground/30' },
    todo: {
        label: 'Needs setup',
        text: 'text-amber-600 dark:text-amber-300/90',
        dot: 'bg-amber-400/80',
        ring: 'border-amber-400/50',
    },
};

// Apple font stack carried over from TypeformSetupView for the large headings.
export const APPLE_FONT_STACK =
    '-apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display", system-ui, sans-serif';

// ---------------------------------------------------------------------------
// Derived helpers
// ---------------------------------------------------------------------------

export interface NodeGroup {
    node: SetupNodeMeta;
    steps: SetupStep[];
    done: number;
}

/** Group steps under their node, preserving node-first-seen order. */
export function groupByNode(steps: SetupStep[], nodes: Record<string, SetupNodeMeta>): NodeGroup[] {
    const order: string[] = [];
    const byNode = new Map<string, SetupStep[]>();
    for (const step of steps) {
        if (!byNode.has(step.nodeId)) {
            byNode.set(step.nodeId, []);
            order.push(step.nodeId);
        }
        byNode.get(step.nodeId)!.push(step);
    }
    return order.map((nodeId) => {
        const grouped = byNode.get(nodeId)!;
        return {
            node: nodes[nodeId],
            steps: grouped,
            done: grouped.filter((s) => s.state === 'done').length,
        };
    });
}

/** Resolve a registry node type to its icon/label/color, with a safe fallback. */
export function resolveNode(nodeType: string): { label: string; Icon?: BrandIconComponent; iconColor: string } {
    const meta = getNodeMetadata(nodeType);
    return {
        label: meta?.label || nodeType || 'Unknown',
        Icon: meta?.Icon,
        iconColor: meta?.iconColor || '',
    };
}

// ---------------------------------------------------------------------------
// Reusable badges & node identity
// ---------------------------------------------------------------------------

/** Square icon well rendering a node's brand icon (or a Settings fallback). */
export function NodeIconWell({
    nodeType,
    className,
    iconClassName,
}: {
    nodeType: string;
    className?: string;
    iconClassName?: string;
}) {
    const { Icon, iconColor } = resolveNode(nodeType);
    return (
        <span
            className={cn(
                'flex shrink-0 items-center justify-center rounded-lg border border-border dark:border-white/[0.06] bg-foreground/[0.05]',
                className,
            )}
        >
            {nodeType === 'variables' ? (
                // Pseudo-nodes match their phase marks — the Settings-gear
                // fallback read as an unrelated system.
                <Braces className={cn('h-4 w-4 text-muted-foreground dark:text-white/40', iconClassName)} />
            ) : nodeType === 'test-run' ? (
                <FlaskConical className={cn('h-4 w-4 text-muted-foreground dark:text-white/40', iconClassName)} />
            ) : Icon ? (
                <BrandIcon Icon={Icon} iconColor={iconColor} className={cn('h-4 w-4', iconClassName)} />
            ) : (
                <Settings className={cn('h-4 w-4 text-muted-foreground dark:text-white/40', iconClassName)} />
            )}
        </span>
    );
}

/** Node icon + label, optionally with the node-type as a subtitle. */
export function NodeBadge({
    node,
    subtitle = false,
    className,
    wellClassName,
}: {
    node: SetupNodeMeta;
    subtitle?: boolean;
    className?: string;
    wellClassName?: string;
}) {
    const { label: typeLabel } = resolveNode(node.nodeType);
    const showSubtitle = subtitle && node.label !== typeLabel;
    return (
        <span className={cn('inline-flex min-w-0 items-center gap-2.5', className)}>
            <NodeIconWell nodeType={node.nodeType} className={cn('h-8 w-8', wellClassName)} />
            <span className="min-w-0 leading-tight">
                <span className="block truncate text-sm font-medium text-foreground">{node.label}</span>
                {showSubtitle && (
                    <span className="block truncate text-[0.6875rem] text-muted-foreground dark:text-white/40">{typeLabel}</span>
                )}
            </span>
        </span>
    );
}

/** Small node chip (icon + label) for "Inputs" / breadcrumb contexts. */
export function NodeChip({
    node,
    className,
    size = 'sm',
}: {
    node: SetupNodeMeta;
    className?: string;
    /** 'sm' for inline "Inputs" chips; 'md' for the prominent header identity. */
    size?: 'sm' | 'md';
}) {
    const md = size === 'md';
    return (
        <span
            className={cn(
                'inline-flex items-center rounded-full border border-border dark:border-white/[0.08] bg-foreground/[0.02]',
                md ? 'max-w-[260px] gap-1.5 px-2.5 py-1' : 'max-w-[160px] gap-1.5 px-2.5 py-1',
                className,
            )}
        >
            <NodeIconWell
                nodeType={node.nodeType}
                className={md ? 'h-5 w-5' : 'h-4 w-4'}
                iconClassName={md ? 'h-3 w-3' : 'h-2.5 w-2.5'}
            />
            <span className={cn('truncate', md ? 'text-[13px] text-foreground/80' : 'text-[0.6875rem] text-muted-foreground dark:text-white/55')}>
                {node.label}
            </span>
        </span>
    );
}

export function StepKindBadge({ kind, className }: { kind: StepKind; className?: string }) {
    const m = STEP_KIND_META[kind];
    return (
        <span
            className={cn(
                'inline-flex w-fit items-center gap-1.5 rounded-md px-2 py-0.5 text-[0.6875rem] font-medium',
                m.bg,
                m.text,
                className,
            )}
        >
            <m.Icon className="h-3 w-3 shrink-0" />
            {m.label}
        </span>
    );
}

/** Status indicator for a step: filled neutral check when done, hollow circle
 *  when todo, accent ring when it is the active/current step. */
export function StepStateMark({
    state,
    current,
    className,
}: {
    state: StepState;
    current?: boolean;
    className?: string;
}) {
    if (state === 'done') {
        return <CheckCircle2 className={cn('h-4 w-4 text-foreground/60', className)} strokeWidth={2} />;
    }
    // Unfilled is the only colored state in the rail: amber, whether it's the
    // current step (ring) or a waiting one (hollow circle).
    if (current) {
        return (
            <span
                className={cn(
                    'flex h-4 w-4 items-center justify-center rounded-full border-2 border-amber-400/70',
                    className,
                )}
            >
                <span className="h-1.5 w-1.5 rounded-full bg-amber-400/90" />
            </span>
        );
    }
    return <Circle className={cn('h-4 w-4 text-amber-500/60 dark:text-amber-300/50', className)} strokeWidth={2} />;
}

export function StepStateDot({
    state,
    current,
    className,
}: {
    state: StepState;
    current?: boolean;
    className?: string;
}) {
    const m = STEP_STATE_META[state];
    return (
        <span className={cn('relative inline-flex h-2 w-2 shrink-0', className)}>
            {current && state === 'todo' && (
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-foreground/40 opacity-70" />
            )}
            <span className={cn('relative inline-flex h-2 w-2 rounded-full', current && state === 'todo' ? 'bg-foreground/80' : m.dot)} />
        </span>
    );
}

/** Compact circular progress ring (track + arc + center %). Used in the
 *  collapsed rail to show overall completion at a glance. */
export function CircularProgress({
    pct,
    size = 40,
    stroke = 3,
    className,
}: {
    pct: number;
    size?: number;
    stroke?: number;
    className?: string;
}) {
    const clamped = Math.max(0, Math.min(1, pct));
    const radius = (size - stroke) / 2;
    const circumference = 2 * Math.PI * radius;
    const offset = circumference * (1 - clamped);
    const complete = clamped >= 1;
    return (
        <div
            className={cn('relative flex items-center justify-center', className)}
            style={{ width: size, height: size }}
        >
            <svg width={size} height={size} className="-rotate-90">
                <circle
                    cx={size / 2}
                    cy={size / 2}
                    r={radius}
                    fill="none"
                    stroke="currentColor"
                    strokeWidth={stroke}
                    className="text-foreground/10"
                />
                <circle
                    cx={size / 2}
                    cy={size / 2}
                    r={radius}
                    fill="none"
                    stroke="currentColor"
                    strokeWidth={stroke}
                    strokeLinecap="round"
                    strokeDasharray={circumference}
                    strokeDashoffset={offset}
                    className={cn(
                        'transition-[stroke-dashoffset] duration-500 ease-out',
                        complete ? 'text-foreground/80' : 'text-foreground/55',
                    )}
                />
            </svg>
            <span className="absolute flex items-baseline text-[0.625rem] font-semibold tabular-nums text-foreground">
                {Math.round(clamped * 100)}
                <span className="text-[0.5rem] text-muted-foreground dark:text-white/40">%</span>
            </span>
        </div>
    );
}

// ---------------------------------------------------------------------------
// Resizable + collapsible side rail — shared by the Split Rail variations. The
// hook owns the width / collapsed state + a drag-to-resize handler; the handle
// and the collapsed icon-strip are small presentational pieces.
// ---------------------------------------------------------------------------

export const RAIL_COLLAPSED_WIDTH = 56;

export interface RailLayout {
    width: number;
    collapsed: boolean;
    resizing: boolean;
    setCollapsed: (c: boolean) => void;
    toggle: () => void;
    startResize: (e: React.MouseEvent) => void;
}

export function useRailLayout(opts?: {
    defaultWidth?: number;
    min?: number;
    max?: number;
    defaultCollapsed?: boolean;
}): RailLayout {
    const defaultWidth = opts?.defaultWidth ?? 288;
    const min = opts?.min ?? 220;
    const max = opts?.max ?? 460;
    const [width, setWidth] = useState(defaultWidth);
    const [collapsed, setCollapsed] = useState(opts?.defaultCollapsed ?? false);
    const [resizing, setResizing] = useState(false);

    // Safety net: if the component unmounts mid-drag, the drag's mouseup cleanup
    // never fires — make sure we never leave the body styles stuck.
    useEffect(
        () => () => {
            document.body.style.userSelect = '';
            document.body.style.cursor = '';
        },
        [],
    );

    const startResize = useCallback(
        (e: React.MouseEvent) => {
            e.preventDefault();
            const startX = e.clientX;
            const startW = width;
            setResizing(true);
            document.body.style.userSelect = 'none';
            document.body.style.cursor = 'col-resize';
            const onMove = (ev: MouseEvent) => {
                setWidth(Math.min(max, Math.max(min, startW + (ev.clientX - startX))));
            };
            const onUp = () => {
                setResizing(false);
                document.body.style.userSelect = '';
                document.body.style.cursor = '';
                window.removeEventListener('mousemove', onMove);
                window.removeEventListener('mouseup', onUp);
            };
            window.addEventListener('mousemove', onMove);
            window.addEventListener('mouseup', onUp);
        },
        [width, min, max],
    );

    return { width, collapsed, resizing, setCollapsed, toggle: () => setCollapsed((c) => !c), startResize };
}

/** Drag handle sitting on the rail's right edge. */
export function RailResizeHandle({
    onMouseDown,
    resizing,
}: {
    onMouseDown: (e: React.MouseEvent) => void;
    resizing?: boolean;
}) {
    return (
        <button
            type="button"
            aria-label="Resize sidebar"
            onMouseDown={onMouseDown}
            className="group absolute right-0 top-0 z-20 flex h-full w-2 translate-x-1/2 cursor-col-resize justify-center focus:outline-none"
        >
            <span
                className={cn(
                    'h-full w-px transition-colors',
                    resizing ? 'bg-foreground/40' : 'bg-transparent group-hover:bg-foreground/25',
                )}
            />
        </button>
    );
}

/** Collapsed rail: a narrow strip of node icons with status dots + an expand
 *  button. Clicking a node expands the rail and jumps to it. */
export function CollapsedNodeRail({
    groups,
    activeNodeId,
    isFilled,
    onExpand,
    onPickNode,
}: {
    groups: NodeGroup[];
    activeNodeId?: string;
    isFilled: (step: SetupStep) => boolean;
    onExpand: () => void;
    onPickNode: (nodeId: string) => void;
}) {
    const allSteps = groups.flatMap((g) => g.steps);
    const overallTotal = allSteps.length;
    const overallDone = allSteps.filter((s) => isFilled(s)).length;
    const overallPct = overallTotal ? overallDone / overallTotal : 0;
    return (
        <TooltipProvider delayDuration={150}>
            <div className="flex flex-1 flex-col items-center gap-1 py-3">
                <Tooltip>
                    <TooltipTrigger asChild>
                        <button
                            type="button"
                            onClick={onExpand}
                            aria-label="Expand sidebar"
                            className="flex h-9 w-9 items-center justify-center rounded-lg text-muted-foreground dark:text-white/45 transition-colors hover:bg-foreground/[0.06] hover:text-foreground/80"
                        >
                            <PanelLeftOpen className="h-4 w-4" />
                        </button>
                    </TooltipTrigger>
                    <TooltipContent
                        side="right"
                        className="border-border dark:border-white/[0.08] bg-sunken text-popover-foreground shadow-xl dark:shadow-black/60"
                    >
                        Expand sidebar
                    </TooltipContent>
                </Tooltip>
                <div className="mt-2 flex flex-1 flex-col items-center gap-1.5 overflow-y-auto scrollbar-subtle">
                    {groups.map((group) => {
                        const done = group.steps.filter((s) => isFilled(s)).length;
                        const total = group.steps.length;
                        const allDone = done === total;
                        const active = group.node.nodeId === activeNodeId;
                        const typeLabel = resolveNode(group.node.nodeType).label;
                        return (
                            <Tooltip key={group.node.nodeId}>
                                <TooltipTrigger asChild>
                                    <button
                                        type="button"
                                        onClick={() => onPickNode(group.node.nodeId)}
                                        className={cn(
                                            'relative rounded-lg p-1 transition-colors',
                                            active ? 'bg-foreground/[0.08]' : 'hover:bg-foreground/[0.04]',
                                        )}
                                    >
                                        <NodeIconWell
                                            nodeType={group.node.nodeType}
                                            className={cn('h-8 w-8', active && 'ring-1 ring-foreground/30')}
                                        />
                                        <span
                                            className={cn(
                                                'absolute -right-0.5 -top-0.5 h-2.5 w-2.5 rounded-full border-2 border-background dark:border-zinc-950',
                                                allDone ? 'bg-foreground/70' : 'bg-foreground/30',
                                            )}
                                        />
                                    </button>
                                </TooltipTrigger>
                                <TooltipContent
                                    side="right"
                                    className="max-w-[240px] border-border dark:border-white/[0.08] bg-sunken text-popover-foreground shadow-xl dark:shadow-black/60"
                                >
                                    <div className="text-sm font-medium text-foreground">{group.node.label}</div>
                                    {group.node.label !== typeLabel && (
                                        <div className="text-xs text-muted-foreground dark:text-white/45">{typeLabel}</div>
                                    )}
                                    {group.node.goal && (
                                        <div className="mt-1 text-xs font-light leading-snug text-muted-foreground dark:text-white/45">
                                            {group.node.goal}
                                        </div>
                                    )}
                                    <div
                                        className={cn(
                                            'mt-1.5 text-[0.6875rem] font-medium tabular-nums',
                                            allDone ? 'text-foreground/80' : 'text-muted-foreground dark:text-white/50',
                                        )}
                                    >
                                        {done} of {total} configured
                                    </div>
                                </TooltipContent>
                            </Tooltip>
                        );
                    })}
                </div>
                <Tooltip>
                    <TooltipTrigger asChild>
                        <div className="mt-2 shrink-0 border-t border-border dark:border-white/[0.06] pt-3">
                            <CircularProgress pct={overallPct} size={40} />
                        </div>
                    </TooltipTrigger>
                    <TooltipContent
                        side="right"
                        className="border-border dark:border-white/[0.08] bg-sunken text-popover-foreground shadow-xl dark:shadow-black/60"
                    >
                        {overallDone} of {overallTotal} steps · {Math.round(overallPct * 100)}% complete
                    </TooltipContent>
                </Tooltip>
            </div>
        </TooltipProvider>
    );
}

export interface SetupNav {
    index: number;
    direction: number;
    step: SetupStep | undefined;
    total: number;
    isFirst: boolean;
    isLast: boolean;
    next: () => void;
    back: () => void;
    goto: (index: number) => void;
}

export function useSetupNav(steps: SetupStep[]): SetupNav {
    const [index, setIndex] = useState(0);
    const [direction, setDirection] = useState(1);
    const total = steps.length;
    const clamped = Math.min(index, Math.max(0, total - 1));
    const next = useCallback(() => {
        setDirection(1);
        setIndex((i) => Math.min(i + 1, total - 1));
    }, [total]);
    const back = useCallback(() => {
        setDirection(-1);
        setIndex((i) => Math.max(i - 1, 0));
    }, []);
    const goto = useCallback(
        (target: number) => {
            setDirection(target > clamped ? 1 : -1);
            setIndex(Math.max(0, Math.min(target, total - 1)));
        },
        [clamped, total],
    );
    return {
        index: clamped,
        direction,
        step: steps[clamped],
        total,
        isFirst: clamped === 0,
        isLast: clamped === total - 1,
        next,
        back,
        goto,
    };
}

