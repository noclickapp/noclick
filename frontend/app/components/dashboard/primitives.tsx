// Shared building blocks for the Dashboard tab designs: marks, eyebrows, stat
// tiles, the runs chart, meters and the small formatters. Black/zinc/white by
// design — brand marks are the only colour, red is reserved for failure, and a
// succeeded thing gets a zinc check, never a green one.
import React, { createContext, useContext, useState, type CSSProperties, type ReactNode } from 'react';
import { ArrowUpRight, Box, Check, Circle, X } from 'lucide-react';
import { cn } from '~/lib/utils';
import { getNodeIconMeta } from '~/lib/nodeIconRegistry';
import { SerializedIcon } from '~/components/shared/SerializedIcon';
import { getCredentialIcon } from '~/utils/credentialIcons';
import { formatCredentialTypeLabel } from '~/utils/credentialTypes';
import type { AgentTurn, AttentionItem, AttentionKind, CredentialEntry, DayBucket, FileEntry, FileSource, NotificationEntry, RunRow, WorkflowRef } from './types';

export const SURFACE = 'rounded-xl border border-border bg-card dark:border-foreground/[0.08] dark:bg-foreground/[0.02]';

/** Props that make a clickable row a real control: role, tab stop, Enter/Space. */
export function clickableRow(onActivate?: () => void) {
    if (!onActivate) return {};
    return {
        role: 'button' as const,
        tabIndex: 0,
        onClick: onActivate,
        onKeyDown: (e: React.KeyboardEvent) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                onActivate();
            }
        },
    };
}
export const HAIRLINE = 'border-border dark:border-foreground/[0.08]';
export const ROW_HOVER = 'transition-colors hover:bg-foreground/[0.03]';

/** Page and grid rhythm, shared by the Bento layout and its loading skeleton so
 *  the placeholder can never drift from the real page. */
export const LAYOUT = {
    pageMaxWidth: 1400,
    pagePad: 'px-7 py-6',
    gridGap: 'gap-[18px]',
    cardPad: 'p-[18px]',
    ledgerCell: 'px-5 py-4',
    greetingGap: 'mb-5',
    ledgerGap: 'mb-4',
} as const;

// ---------------------------------------------------------------------------
// The action seam. Sections only ever call these; the product wires them to
// sockets and navigation, the design lab to notes. Optional members hide their
// affordance when absent, so a surface never shows a button that does nothing.

export interface DashboardActions {
    /** Attention items answered locally, hidden until the next fetch confirms. */
    dismissed: ReadonlySet<string>;
    openWorkflow: (workflow: WorkflowRef, nodeId?: string) => void;
    respondApproval: (item: AttentionItem, decision: 'approved' | 'rejected', values: Record<string, unknown>) => void;
    answerAsk: (item: AttentionItem, answers: Record<string, unknown>) => void;
    /** Resume the builder without an answer (the wizard's Skip). */
    dismissAsk?: (item: AttentionItem) => void;
    /** Mint a public /b/ link for the ask; resolves to its URL. */
    shareAsk?: (item: AttentionItem) => Promise<string | null>;
    decideProposal: (item: AttentionItem, decision: 'approved' | 'dismissed') => void;
    copyLink: (item: AttentionItem) => void;
    openLink: (item: AttentionItem) => void;
    cancelCredentialRequest: (item: AttentionItem) => void;
    resendCredentialRequest?: (item: AttentionItem) => void;
    reconnectCredential: (target: { credentialId?: string; credentialType?: string; name?: string }) => void;
    openRun: (run: RunRow) => void;
    /** Open a run's Story popup by execution id (turns know their execution). */
    /** Open the run's Story popup (persisted executions only). */
    openExecution?: (run: RunRow) => void;
    retryRun?: (run: RunRow) => void;
    loadOlderRuns?: () => void;
    openConversation: (turn: AgentTurn) => void;
    openFile: (file: FileEntry, source: FileSource) => void;
    uploadTo?: (source: FileSource) => void;
    /** Remove one file from a writable place; rejects with the reason. */
    deleteFile?: (file: FileEntry, source: FileSource) => Promise<void>;
    /** Open THIS credential's dialog (the same one the command palette opens). */
    manageCredential: (credential: CredentialEntry) => void;
    /** Settings → Credentials, for the "all of them" hand-off. */
    openCredentialsSettings: () => void;
    /** Confirm-and-delete a credential (the same dialog Settings uses). */
    deleteCredential?: (credential: CredentialEntry) => void;
    connectAccount: () => void;
    topUp?: () => void;
    openUsage: () => void;
    markNotificationsRead: (ids?: string[]) => void;
    openNotification: (notification: NotificationEntry) => void;
    openPreferences: () => void;
}

const noop = () => {};
export const DashboardActionsContext = createContext<DashboardActions>({
    dismissed: new Set(),
    openWorkflow: noop,
    respondApproval: noop,
    answerAsk: noop,
    decideProposal: noop,
    copyLink: noop,
    openLink: noop,
    cancelCredentialRequest: noop,
    reconnectCredential: noop,
    openRun: noop,
    openConversation: noop,
    openFile: noop,
    manageCredential: noop,
    openCredentialsSettings: noop,
    connectAccount: noop,
    openUsage: noop,
    markNotificationsRead: noop,
    openNotification: noop,
    openPreferences: noop,
});
export const useDashboardActions = () => useContext(DashboardActionsContext);

// ---------------------------------------------------------------------------
// Formatters

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const pad2 = (n: number) => String(n).padStart(2, '0');

/** "3m ago" · "2h ago" · "yesterday" · "Aug 24". Relative to the fixture clock. */
export function relTime(iso: string, now: string): string {
    const t = Date.parse(iso);
    const n = Date.parse(now);
    if (Number.isNaN(t) || Number.isNaN(n)) return '';
    const diff = n - t;
    const future = diff < 0;
    const abs = Math.abs(diff);
    const m = Math.round(abs / 60_000);
    if (m < 1) return 'now';
    if (m < 60) return future ? `in ${m}m` : `${m}m ago`;
    const hrs = Math.round(m / 60);
    if (hrs < 24) return future ? `in ${hrs}h` : `${hrs}h ago`;
    const dd = Math.round(hrs / 24);
    if (dd === 1) return future ? 'tomorrow' : 'yesterday';
    if (dd < 7) return future ? `in ${dd}d` : `${dd}d ago`;
    const dt = new Date(t);
    return `${MONTHS[dt.getMonth()]} ${dt.getDate()}`;
}

export function clockLabel(iso: string): string {
    const dt = new Date(iso);
    return `${pad2(dt.getHours())}:${pad2(dt.getMinutes())}`;
}

export function dateLabel(iso: string): string {
    const dt = new Date(iso);
    return `${MONTHS[dt.getMonth()]} ${dt.getDate()}, ${pad2(dt.getHours())}:${pad2(dt.getMinutes())}`;
}

export function fmtBytes(n: number): string {
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(n < 10 * 1024 ? 1 : 0)} KB`;
    if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
    return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

export function fmtDuration(ms: number | null): string {
    if (ms == null) return '';
    if (ms < 1000) return `${ms}ms`;
    const s = Math.round(ms / 1000);
    if (s < 60) return `${s}s`;
    const m = Math.floor(s / 60);
    const rest = s % 60;
    if (m < 60) return rest ? `${m}m ${rest}s` : `${m}m`;
    return `${Math.floor(m / 60)}h ${m % 60}m`;
}

export function compactNumber(n: number): string {
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
    if (n >= 10_000) return `${(n / 1000).toFixed(1)}K`;
    return n.toLocaleString('en-US');
}

export function fmtCredits(n: number): string {
    if (n >= 100) return Math.round(n).toLocaleString('en-US');
    if (n >= 10) return n.toFixed(1);
    return n.toFixed(2);
}

export const ATTENTION_KIND_LABEL: Record<AttentionKind, string> = {
    approval: 'Approval',
    builder_ask: 'Builder question',
    builder_prompt: 'Agent proposal',
    bridge_link: 'Connect account',
    credential_request: 'Credential request',
    credential_dead: 'Disconnected',
    trigger_broken: 'Trigger broken',
};

/** Items a human must decide; the rest are things to fix. */
export const DECISION_KINDS: ReadonlySet<AttentionKind> = new Set([
    'approval',
    'builder_ask',
    'builder_prompt',
]);

export function harnessLabel(model: string): string {
    switch (model) {
        case 'claude-code':
            return 'Claude Code';
        case 'codex':
            return 'Codex';
        case 'opencode':
            return 'OpenCode';
        case 'openclaw':
            return 'OpenClaw';
        default:
            return model.includes('hermes') ? 'Hermes' : model;
    }
}

export function agentMarkType(model: string): string {
    const kinds = ['claude-code', 'codex', 'opencode', 'openclaw'];
    if (kinds.includes(model)) return `agent:${model}`;
    if (model.includes('hermes')) return 'agent:hermes';
    return 'agent';
}

// ---------------------------------------------------------------------------
// Marks

const MARK_SIZE = { xs: 'h-3.5 w-3.5', sm: 'h-4 w-4', md: 'h-5 w-5', lg: 'h-7 w-7' } as const;
export type MarkSize = keyof typeof MARK_SIZE;

/** A node's brand mark from the serialized catalog; a quiet cube when unknown. */
export function NodeMark({
    type,
    size = 'sm',
    className,
    title,
}: {
    type: string;
    size?: MarkSize;
    className?: string;
    title?: string;
}) {
    const meta = getNodeIconMeta(type);
    if (!meta?.iconHtml) {
        return <Box className={cn(MARK_SIZE[size], 'shrink-0 text-foreground/60 dark:text-foreground/40', className)} aria-label={title} />;
    }
    return (
        <span className={cn('inline-flex shrink-0 items-center justify-center', MARK_SIZE[size], className)} title={title ?? meta.label}>
            <SerializedIcon html={meta.iconHtml} iconColor={meta.iconColor} className="h-full w-full" />
        </span>
    );
}

export function nodeLabel(type: string): string {
    return getNodeIconMeta(type)?.label ?? type;
}

/** A credential's provider mark: the node's brand mark when the node type is
 *  known, else the credential-type icon the Settings list uses. */
export function CredentialMark({ credentialType, nodeType, size = 'sm', className }: { credentialType: string; nodeType?: string | null; size?: MarkSize; className?: string }) {
    if (nodeType && getNodeIconMeta(nodeType)?.iconHtml) return <NodeMark type={nodeType} size={size} className={className} />;
    const { Icon, iconColor } = getCredentialIcon(credentialType);
    const isTw = iconColor.startsWith('text-');
    return (
        <span className={cn('inline-flex shrink-0 items-center justify-center', MARK_SIZE[size], isTw ? iconColor : !iconColor && 'text-foreground/70', className)} style={!isTw && iconColor ? { color: iconColor } : undefined}>
            <Icon className="h-full w-full" />
        </span>
    );
}

export function credentialLabel(credentialType: string, nodeType?: string | null): string {
    if (nodeType && getNodeIconMeta(nodeType)) return nodeLabel(nodeType);
    return formatCredentialTypeLabel(credentialType);
}

/** The marks that identify a workflow, in a tight row with +N overflow. */
export function MarkRow({ types, size = 'sm', max = 4, className, hideRest = false }: { types: string[]; size?: MarkSize; max?: number; className?: string; hideRest?: boolean }) {
    const shown = types.slice(0, max);
    const rest = types.length - shown.length;
    return (
        <span className={cn('inline-flex items-center gap-1.5', className)}>
            {shown.map((t, i) => (
                <NodeMark key={`${t}-${i}`} type={t} size={size} />
            ))}
            {rest > 0 && !hideRest && <span className="text-[10.5px] tabular-nums text-foreground/60 dark:text-foreground/40">+{rest}</span>}
        </span>
    );
}

/** Workflow identity for a row: marks then the name, as a click-through. */
export function WorkflowLine({ workflow, size = 'xs', className, muted = true, maxMarks = 3, hideRest = false, showMarks = true }: { workflow: WorkflowRef; size?: MarkSize; className?: string; muted?: boolean; maxMarks?: number; hideRest?: boolean; showMarks?: boolean }) {
    const { openWorkflow } = useDashboardActions();
    return (
        <button
            type="button"
            onClick={(e) => {
                e.stopPropagation();
                openWorkflow(workflow);
            }}
            className={cn(
                'group/wf inline-flex min-w-0 items-center gap-1.5 text-left transition-colors hover:text-foreground',
                muted ? 'text-foreground/70 dark:text-foreground/50' : 'text-foreground',
                className
            )}
        >
            {showMarks && <MarkRow types={workflow.marks} size={size} max={maxMarks} hideRest={hideRest} />}
            <span className="truncate text-[12px]">{workflow.name}</span>
            <ArrowUpRight className="h-3 w-3 shrink-0 opacity-0 transition-opacity group-hover/wf:opacity-60" />
        </button>
    );
}

// ---------------------------------------------------------------------------
// Typography + chrome

export function Eyebrow({ children, right, className }: { children: ReactNode; right?: ReactNode; className?: string }) {
    return (
        <div className={cn('flex items-center justify-between gap-3', className)}>
            <span className="text-[11px] font-semibold uppercase tracking-[0.1em] text-foreground/55 dark:text-foreground/35">{children}</span>
            {right}
        </div>
    );
}

/** A labelled text link — the configured affordance style (no border, no box). */
/** A visible but quiet control: the same borderless fill as the active filter
 *  chip and the navbar tab. For navigation that must be findable (the
 *  drill-down's way back) without competing with the page's primary actions. */
export function SoftButton({ children, onClick, className }: { children: ReactNode; onClick?: () => void; className?: string }) {
    return (
        <button
            type="button"
            onClick={onClick}
            className={cn(
                'inline-flex h-8 items-center gap-1.5 rounded-md bg-foreground/[0.07] px-3 text-[12.5px] font-medium text-foreground transition-colors hover:bg-foreground/[0.12]',
                className
            )}
        >
            {children}
        </button>
    );
}

export function TextLink({ children, onClick, className, icon = true }: { children: ReactNode; onClick?: () => void; className?: string; icon?: boolean }) {
    return (
        <button
            type="button"
            onClick={onClick}
            className={cn(
                'inline-flex items-center gap-1 text-[11.5px] text-foreground/65 dark:text-foreground/45 transition-colors hover:text-foreground',
                className
            )}
        >
            {children}
            {icon && <ArrowUpRight className="h-3 w-3" />}
        </button>
    );
}

/** Section title row: name, optional count, and the drill-down link. */
export function SectionHeader({
    title,
    count,
    meta,
    onOpen,
    openLabel = 'See all',
    className,
    as = 'eyebrow',
}: {
    title: string;
    count?: number;
    meta?: ReactNode;
    onOpen?: () => void;
    openLabel?: string;
    className?: string;
    as?: 'eyebrow' | 'title';
}) {
    return (
        <div className={cn('flex items-baseline justify-between gap-3', className)}>
            <div className="flex min-w-0 items-baseline gap-2">
                {as === 'eyebrow' ? (
                    <span className="text-[11px] font-semibold uppercase tracking-[0.1em] text-foreground/55 dark:text-foreground/35">{title}</span>
                ) : (
                    <span className="text-[15px] font-semibold tracking-tight text-foreground">{title}</span>
                )}
                {count != null && count > 0 && (
                    <span className="text-[11px] tabular-nums text-foreground/55 dark:text-foreground/35">{count}</span>
                )}
                {meta && <span className="truncate text-[11px] text-foreground/55 dark:text-foreground/35">{meta}</span>}
            </div>
            {onOpen && <TextLink onClick={onOpen}>{openLabel}</TextLink>}
        </div>
    );
}

export function KindPill({ children, tone = 'neutral', className }: { children: ReactNode; tone?: 'neutral' | 'failure' | 'live'; className?: string }) {
    return (
        <span
            className={cn(
                'inline-flex items-center gap-1 rounded-md px-1.5 py-[1px] text-[10.5px] font-medium',
                tone === 'failure'
                    ? 'bg-red-500/10 text-red-600 dark:text-red-400'
                    : tone === 'live'
                      ? 'bg-foreground/[0.08] text-foreground'
                      : 'bg-foreground/[0.06] text-foreground/75 dark:text-foreground/60',
                className
            )}
        >
            {children}
        </span>
    );
}

export function EmptyState({ title, hint, className }: { title: string; hint?: string; className?: string }) {
    return (
        <div className={cn('py-8 text-center', className)}>
            <p className="m-0 text-[13px] text-foreground/75 dark:text-foreground/60">{title}</p>
            {hint && <p className="m-0 mt-1 text-[11.5px] text-foreground/55 dark:text-foreground/35">{hint}</p>}
        </div>
    );
}

// ---------------------------------------------------------------------------
// Status

export type VerdictStatus = 'ok' | 'failed' | 'running' | 'waiting' | 'idle';

/** The verdict glyph: zinc check, red cross, a live dot, a hollow circle. */
export function Verdict({ status, className, label }: { status: VerdictStatus; className?: string; label?: string }) {
    const base = cn('inline-flex shrink-0 items-center justify-center', className);
    let glyph: ReactNode;
    switch (status) {
        case 'ok':
            glyph = <Check className="h-3.5 w-3.5 text-foreground/70 dark:text-foreground/50" strokeWidth={2.25} />;
            break;
        case 'failed':
            glyph = <X className="h-3.5 w-3.5 text-red-600 dark:text-red-400" strokeWidth={2.25} />;
            break;
        case 'running':
            glyph = <LiveDot />;
            break;
        case 'waiting':
            glyph = <Circle className="h-3 w-3 text-foreground/70" strokeWidth={2} />;
            break;
        default:
            glyph = <Circle className="h-2.5 w-2.5 text-foreground/40 dark:text-foreground/25" strokeWidth={2} />;
    }
    return (
        <span className={base} title={label}>
            {glyph}
        </span>
    );
}

export function LiveDot({ className }: { className?: string }) {
    return (
        <span className={cn('relative inline-flex h-2.5 w-2.5', className)}>
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-foreground/40" />
            <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-foreground" />
        </span>
    );
}

// ---------------------------------------------------------------------------
// Figures

/** Stat tile: label · value · optional delta · optional 14-point sparkline. */
export function StatTile({
    label,
    value,
    delta,
    trend,
    tone = 'neutral',
    onClick,
    className,
    hero = false,
}: {
    label: string;
    value: string;
    delta?: { text: string; good?: boolean };
    trend?: number[];
    tone?: 'neutral' | 'failure' | 'attention';
    onClick?: () => void;
    className?: string;
    hero?: boolean;
}) {
    const Tag = onClick ? 'button' : 'div';
    return (
        <Tag
            type={onClick ? 'button' : undefined}
            onClick={onClick}
            className={cn(
                'flex min-w-0 flex-col items-start gap-1 text-left',
                onClick && 'group/stat cursor-pointer',
                className
            )}
        >
            <span className="text-[11px] font-medium text-foreground/65 dark:text-foreground/45">{label}</span>
            <span className="flex w-full items-end justify-between gap-3">
                <span
                    className={cn(
                        'leading-none tracking-tight',
                        hero ? 'text-[48px] font-semibold' : 'text-[22px] font-semibold',
                        tone === 'failure' && 'text-red-600 dark:text-red-400',
                        tone === 'attention' && 'text-foreground'
                    )}
                >
                    {value}
                </span>
                {trend && <Sparkline values={trend} className="mb-[3px] shrink-0" />}
            </span>
            {delta && (
                <span className={cn('text-[11px]', delta.good === false ? 'text-red-600 dark:text-red-400' : 'text-foreground/60 dark:text-foreground/40')}>
                    {delta.text}
                </span>
            )}
        </Tag>
    );
}

/** 14-point sparkline, de-emphasis ink with the last point marked. */
export function Sparkline({ values, width = 72, height = 22, className }: { values: number[]; width?: number; height?: number; className?: string }) {
    if (!values.length) return null;
    const max = Math.max(1, ...values);
    const stepX = values.length > 1 ? width / (values.length - 1) : width;
    const pts = values.map((v, i) => [i * stepX, height - 2 - (v / max) * (height - 4)] as const);
    const path = pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)}`).join(' ');
    const [lx, ly] = pts[pts.length - 1];
    return (
        <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className={cn('overflow-visible', className)} aria-hidden>
            <path d={path} fill="none" stroke="hsl(var(--foreground) / 0.3)" strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
            <circle cx={lx} cy={ly} r={2.5} fill="hsl(var(--foreground))" stroke="hsl(var(--background))" strokeWidth={2} />
        </svg>
    );
}

/** Stacked columns of ok/failed runs per day. Two series → legend present;
    failures wear the one reserved status colour, successes are ink. */
export function RunsColumns({ days, height = 92, className, showLegend = true, now }: { days: DayBucket[]; height?: number; className?: string; showLegend?: boolean; now?: string }) {
    const [hover, setHover] = useState<number | null>(null);
    const max = Math.max(1, ...days.map((b) => b.ok + b.failed));
    const plotH = height - 18; // leave the x-axis band inside the box
    const n = days.length;
    const total = days.reduce((a, b) => a + b.ok + b.failed, 0);
    if (!total) {
        return (
            <div className={cn('flex items-center justify-center text-[11.5px] text-foreground/55 dark:text-foreground/35', className)} style={{ height }}>
                No runs in this window
            </div>
        );
    }
    const gap = 2;
    const labelEvery = n > 10 ? 7 : 1;
    return (
        <div className={cn('relative', className)}>
            <div className="flex items-end" style={{ height: plotH, gap }} onMouseLeave={() => setHover(null)}>
                {days.map((b, i) => {
                    const all = b.ok + b.failed;
                    const okH = (b.ok / max) * plotH;
                    const failH = (b.failed / max) * plotH;
                    const active = hover === i;
                    return (
                        <div
                            key={b.date}
                            className="relative flex h-full flex-1 cursor-default flex-col justify-end"
                            style={{ maxWidth: 24 }}
                            onMouseEnter={() => setHover(i)}
                        >
                            {b.failed > 0 && (
                                <div
                                    className="w-full rounded-t-[4px] text-red-600 dark:text-red-400"
                                    style={{ height: Math.max(failH, 2), background: 'currentColor', opacity: active ? 1 : 0.85 }}
                                />
                            )}
                            {b.ok > 0 && (
                                <div
                                    className={cn('w-full', b.failed > 0 ? 'mt-[2px]' : 'rounded-t-[4px]')}
                                    style={{ height: Math.max(okH, 2), background: `hsl(var(--foreground) / ${active ? 0.6 : 0.28})` }}
                                />
                            )}
                            {all === 0 && <div className="w-full" style={{ height: 2, background: 'hsl(var(--foreground) / 0.1)' }} />}
                            {active && (
                                <div className="pointer-events-none absolute bottom-full left-1/2 z-10 mb-2 -translate-x-1/2 whitespace-nowrap rounded-md border border-border dark:border-foreground/10 bg-popover px-2 py-1 text-[11px] text-foreground shadow-md">
                                    <span className="text-foreground/70 dark:text-foreground/50">{dayShort(b.date)}</span>
                                    <span className="ml-2 tabular-nums">{all} runs</span>
                                    {b.failed > 0 && <span className="ml-2 tabular-nums text-red-600 dark:text-red-400">{b.failed} failed</span>}
                                </div>
                            )}
                        </div>
                    );
                })}
            </div>
            <div className="mt-1 flex" style={{ gap }}>
                {days.map((b, i) => (
                    <div key={b.date} className="flex-1 overflow-visible whitespace-nowrap text-[10px] tabular-nums text-foreground/45 dark:text-foreground/30" style={{ maxWidth: 24 }}>
                        {(i === 0 || (n - 1 - i) % labelEvery === 0) && n - 1 - i !== 0 ? dayShort(b.date) : i === n - 1 ? 'today' : ''}
                    </div>
                ))}
            </div>
            {showLegend && (
                <div className="mt-2 flex items-center gap-4 text-[11px] text-foreground/65 dark:text-foreground/45">
                    <span className="inline-flex items-center gap-1.5">
                        <span className="h-2 w-2 rounded-[2px]" style={{ background: 'hsl(var(--foreground) / 0.28)' }} /> Succeeded
                    </span>
                    <span className="inline-flex items-center gap-1.5">
                        <span className="h-2 w-2 rounded-[2px] bg-red-600 dark:bg-red-400" /> Failed
                    </span>
                    {now && <span className="ml-auto text-foreground/45 dark:text-foreground/30">Last {n} days</span>}
                </div>
            )}
        </div>
    );
}

function dayShort(date: string): string {
    const [, m, d] = date.split('-').map(Number);
    return `${MONTHS[m - 1]} ${d}`;
}

/** A single ratio against a limit. Fill is ink; the last tenth turns red. */
export function Meter({ value, max, className, style }: { value: number; max: number; className?: string; style?: CSSProperties }) {
    const pct = Math.max(0, Math.min(1, max ? value / max : 0));
    const critical = pct >= 0.9;
    return (
        <div className={cn('h-1.5 w-full overflow-hidden rounded-full', className)} style={{ background: 'hsl(var(--foreground) / 0.08)', ...style }}>
            <div
                className={cn('h-full rounded-full', critical && 'bg-red-600 dark:bg-red-400')}
                style={{ width: `${pct * 100}%`, ...(critical ? {} : { background: 'hsl(var(--foreground) / 0.55)' }) }}
            />
        </div>
    );
}

/** Small ink bar for ranked lists (credits by workflow, files by source). */
export function InkBar({ value, max, className }: { value: number; max: number; className?: string }) {
    const pct = Math.max(0, Math.min(1, max ? value / max : 0));
    return (
        <div className={cn('h-1 w-full overflow-hidden rounded-full', className)} style={{ background: 'hsl(var(--foreground) / 0.06)' }}>
            <div className="h-full rounded-full" style={{ width: `${pct * 100}%`, background: 'hsl(var(--foreground) / 0.4)' }} />
        </div>
    );
}
