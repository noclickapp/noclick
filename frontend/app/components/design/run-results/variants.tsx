/* The run-results Story view — one column in reading order (came in → what
   the agent did → what went out → also ran). Zinc discipline: success is
   silent, red is reserved for failure, brand marks carry the only color, and
   native app frames stand alone on the zinc-950 ground. Rendered by the
   production RunResultsDialog. */

import { useMemo, useState } from 'react';
import {
    Bot,
    Check,
    ChevronDown,
    Clock,
    FileText,
    Globe,
    History,
    Loader2,
    Mail,
    Minus,
    Play,
    Plug,
    Settings2,
    Terminal,
    Wrench,
    X,
    Zap,
} from 'lucide-react';
import { MarkdownRenderer } from '~/components/chat/MarkdownRendererLazy';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '~/components/ui/tooltip';
import { SerializedIcon } from '~/components/shared/SerializedIcon';
import { cn } from '~/lib/utils';
import { getNodeIconMeta } from '~/lib/nodeIconRegistry';
import { InboundMessage, OutboundMessage, isEmailShaped } from '~/components/design/rehearsal/native';
import { resolveAppTheme } from '~/components/design/rehearsal/appThemes';
import type { Mark } from '~/components/design/rehearsal/variants';
import { ErrorActionButton, type ErrorAction } from '~/components/workflow/ErrorActionButton';
import { IODataDisplay } from '~/components/workflow/IODataDisplay';
import {
    deriveNodeDetail,
    humanizeOp,
    outcomeModeFor,
    slugOfType,
    type RunStory,
    type StoryNodeResult,
    type StoryRow,
    type StorySend,
    type StoryToolProvider,
} from './runStory';

/* ---------------------------------------------------------- run switcher */

/** One run in the switcher — the fields WorkflowExecutionLog really carries
    (the lab fabricates the same shape). */
export interface SwitcherRun {
    id: string;
    iso?: string;
    failed?: boolean;
    running?: boolean;
    durationLabel?: string;
    /** Provider slug for a brand mark, or a kind: 'manual'|'cron'|'webhook'|
        'email'|'form'|'run'. */
    triggerSlug?: string;
    triggerTooltip?: string;
    nodes?: number;
    error?: string;
}

export interface RunSwitcherData {
    runs: SwitcherRun[];
    currentId: string | null;
    latestId?: string;
    hasMore?: boolean;
    loadingMore?: boolean;
    onLoadMore?: () => void;
    onSelect: (id: string) => void;
}

export interface RunVariantProps {
    story: RunStory;
    /** Marks keyed by provider slug AND full node type (buildStoryIcons). */
    icons: Record<string, Mark>;
    onOpenConfig?: (nodeId: string) => void;
    onClose?: () => void;
    /** Run history for the header switcher; absent hides the pill. */
    switcher?: RunSwitcherData;
    onDontShowAgain?: () => void;
    /** Host renders its own close (Radix DialogContent's X) — skip ours and
        clear space for it. */
    builtinClose?: boolean;
}

/* ------------------------------------------------------------- shared */

/** Quiet raised card on the popup's zinc-950 ground — foreground washes so
    both themes layer correctly without pinned hexes. */
const SURFACE = 'rounded-xl border border-foreground/[0.06] bg-foreground/[0.02]';

type ToolRow = Extract<StoryRow, { kind: 'tool' }>;

const sec = (ms?: number) =>
    ms === undefined ? '' : ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;

function Glyph({ mark, className }: { mark?: Mark; className?: string }) {
    if (mark?.node) return <span className={cn('inline-flex', className)}>{mark.node}</span>;
    if (!mark?.iconHtml) return null;
    return <SerializedIcon html={mark.iconHtml} iconColor={mark.iconColor} className={className} />;
}

/** A node/provider mark with the same fallbacks the canvas uses: amber bolt
    for unmarked triggers, bot for everything else. */
function NodeMark({
    slug,
    icons,
    className = 'h-4 w-4 shrink-0',
    fallback = 'bot',
}: {
    slug: string;
    icons: RunVariantProps['icons'];
    className?: string;
    fallback?: 'bot' | 'bolt';
}) {
    const mark = icons[slug];
    if (mark?.node || mark?.iconHtml) return <Glyph mark={mark} className={className} />;
    if (fallback === 'bolt')
        return <Zap className={cn(className, 'text-amber-600 dark:text-amber-400')} fill="currentColor" />;
    return <Bot className={cn(className, 'text-muted-foreground')} />;
}

function StepMark({
    row,
    icons,
    className = 'h-3.5 w-3.5 shrink-0',
}: {
    row: ToolRow;
    icons: RunVariantProps['icons'];
    className?: string;
}) {
    const mark = row.provider ? icons[row.provider] : undefined;
    if (mark?.node || mark?.iconHtml) return <Glyph mark={mark} className={className} />;
    const Generic = row.glyph === 'terminal' ? Terminal : row.glyph === 'globe' ? Globe : Plug;
    return <Generic className={cn(className, 'text-foreground/45')} />;
}

function Eyebrow({ children, right }: { children: React.ReactNode; right?: React.ReactNode }) {
    return (
        <div className="mb-2 flex items-center justify-between gap-3 px-0.5">
            <span className="text-[11px] font-semibold uppercase tracking-[0.1em] text-foreground/35">
                {children}
            </span>
            {right}
        </div>
    );
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const pad2 = (n: number) => String(n).padStart(2, '0');

/** Local "Aug 24, 09:41". */
function dateLabel(iso: string): string {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return `${MONTHS[d.getMonth()]} ${d.getDate()}, ${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
}

/** The verdict, in zinc: success is calm ("Finished" in plain ink), failure is
    the one word that earns red. */
function Verdict({ story }: { story: RunStory }) {
    const { stats } = story;
    return (
        <span className="flex flex-wrap items-center gap-1.5 text-[13px]">
            {stats.failed ? (
                <span className="font-medium text-red-600 dark:text-red-400">Failed</span>
            ) : (
                <span className="font-medium text-foreground/80">Finished</span>
            )}
            {stats.durationLabel && (
                <span className="text-muted-foreground/70">in {stats.durationLabel}</span>
            )}
            {stats.toolCalls > 0 && (
                <span className="text-muted-foreground/60">
                    · {stats.toolCalls} tool call{stats.toolCalls === 1 ? '' : 's'}
                </span>
            )}
            {stats.sends > 0 && <span className="text-muted-foreground/60">· {stats.sends} sent</span>}
        </span>
    );
}

/** The mark of what fired a run: a brand logo when the slug names a provider,
    a kind glyph (manual/schedule/webhook/email/form) when that's all the
    execution log knows. */
function RunTriggerGlyph({
    slug,
    icons,
    className = 'h-3 w-3 shrink-0',
}: {
    slug?: string;
    icons: RunVariantProps['icons'];
    className?: string;
}) {
    switch (slug) {
        case undefined:
        case 'manual':
        case 'run':
            return <Play className={cn(className, 'text-foreground/35')} />;
        case 'cron':
            return <Clock className={cn(className, 'text-foreground/35')} />;
        case 'webhook':
            return <Zap className={cn(className, 'text-foreground/35')} />;
        case 'email':
            return <Mail className={cn(className, 'text-foreground/35')} />;
        case 'form':
            return <FileText className={cn(className, 'text-foreground/35')} />;
        default:
            return <NodeMark slug={slug} icons={icons} className={className} fallback="bolt" />;
    }
}

/** The run switcher: "Latest run · date" opens the history — each past run a
    status glyph, date, trigger mark, and what it amounted to. Exported so the
    dialog can keep it visible while a switched run's results load. */
export function RunSwitcher({
    data,
    icons,
    fallbackIso,
}: {
    data: RunSwitcherData;
    icons: RunVariantProps['icons'];
    fallbackIso?: string;
}) {
    const [open, setOpen] = useState(false);
    const current = data.runs.find((r) => r.id === data.currentId);
    const isLatest =
        data.currentId !== null &&
        (data.latestId === undefined || data.currentId === data.latestId);
    const pillIso = current?.iso ?? fallbackIso;
    return (
        <div className="relative">
            <button
                type="button"
                title="View older runs"
                onClick={() => setOpen((v) => !v)}
                className="group inline-flex items-center gap-1.5 rounded-lg border border-foreground/10 px-2.5 py-1.5 text-[12px] transition-colors hover:border-foreground/20 hover:bg-foreground/[0.04]"
            >
                <History className="h-3 w-3 text-foreground/45" />
                <span className="font-medium text-foreground/70">{isLatest ? 'Latest run' : 'Run'}</span>
                {pillIso && <span className="text-foreground/35">· {dateLabel(pillIso)}</span>}
                <ChevronDown
                    className={cn(
                        'h-3 w-3 text-foreground/35 transition-all group-hover:text-foreground/70',
                        open && 'rotate-180'
                    )}
                />
            </button>
            {open && (
                <TooltipProvider delayDuration={200}>
                    <button
                        aria-label="Close run switcher"
                        onClick={() => setOpen(false)}
                        className="fixed inset-0 z-10 cursor-default"
                    />
                    <div
                        className="absolute right-0 z-20 mt-1.5 overflow-hidden rounded-xl border border-border bg-popover/95 shadow-2xl backdrop-blur-md dark:bg-zinc-950/95"
                        style={{ width: 344 }}
                    >
                        <p className="m-0 border-b border-foreground/[0.06] px-3 py-2 text-[10.5px] font-semibold uppercase tracking-[0.08em] text-foreground/35">
                            Runs
                        </p>
                        {/* Inset, rounded highlights — the same register as the
                            trace rows; a full-bleed sharp bar read as a different
                            component living in the same menu. */}
                        <div className="scrollbar-subtle max-h-64 overflow-y-auto px-1.5 py-1.5">
                            {data.runs.length === 0 && !data.loadingMore && (
                                <p className="m-0 px-2 py-3 text-[12px] text-foreground/40">No runs yet.</p>
                            )}
                            {data.runs.map((r) => (
                                <button
                                    key={r.id}
                                    type="button"
                                    onClick={() => {
                                        setOpen(false);
                                        data.onSelect(r.id);
                                    }}
                                    className={cn(
                                        'flex w-full items-center gap-2.5 rounded-lg px-2 py-2 text-left transition-colors',
                                        r.id === data.currentId ? 'bg-foreground/[0.06]' : 'hover:bg-foreground/[0.03]'
                                    )}
                                >
                                    <span className="flex w-3.5 shrink-0 justify-center">
                                        {r.running ? (
                                            <Loader2 className="h-3.5 w-3.5 animate-spin text-foreground/40" />
                                        ) : r.failed ? (
                                            <X className="h-3.5 w-3.5 text-red-500 dark:text-red-400" />
                                        ) : (
                                            <Check className="h-3.5 w-3.5 text-foreground/40" />
                                        )}
                                    </span>
                                    <span className="min-w-0 flex-1">
                                        <span className="flex items-center gap-1.5">
                                            <span className="truncate text-[12.5px] text-foreground/85">
                                                {r.iso ? dateLabel(r.iso) : r.id.slice(0, 8)}
                                            </span>
                                            <Tooltip>
                                                <TooltipTrigger asChild>
                                                    <span
                                                        data-testid="run-trigger-mark"
                                                        className="inline-flex shrink-0 cursor-default"
                                                    >
                                                        <RunTriggerGlyph slug={r.triggerSlug} icons={icons} />
                                                    </span>
                                                </TooltipTrigger>
                                                {/* z-[70]: inside the Radix dialog the portaled
                                                    tooltip must clear the dialog's own layer. */}
                                                <TooltipContent side="top" className="z-[70] text-[11px]">
                                                    {r.triggerTooltip ?? 'Started manually'}
                                                </TooltipContent>
                                            </Tooltip>
                                        </span>
                                        <span className="block truncate text-[10.5px] text-foreground/35">
                                            {r.running ? (
                                                'running…'
                                            ) : r.failed && r.error ? (
                                                <>
                                                    {r.durationLabel} ·{' '}
                                                    <span className="text-red-400">{r.error}</span>
                                                </>
                                            ) : (
                                                [
                                                    r.durationLabel,
                                                    r.nodes !== undefined
                                                        ? `${r.nodes} node${r.nodes === 1 ? '' : 's'}`
                                                        : undefined,
                                                ]
                                                    .filter(Boolean)
                                                    .join(' · ')
                                            )}
                                        </span>
                                    </span>
                                    {data.latestId !== undefined && r.id === data.latestId && (
                                        <span className="shrink-0 rounded-md border border-foreground/12 px-1.5 py-px text-[9.5px] font-medium uppercase tracking-[0.08em] text-foreground/40">
                                            latest
                                        </span>
                                    )}
                                </button>
                            ))}
                            {data.loadingMore && (
                                <p className="m-0 flex items-center gap-2 px-2 py-2 text-[11.5px] text-foreground/40">
                                    <Loader2 className="h-3 w-3 animate-spin" /> Loading…
                                </p>
                            )}
                        </div>
                        {data.hasMore && !data.loadingMore && (
                            <button
                                type="button"
                                onClick={() => data.onLoadMore?.()}
                                className="w-full border-t border-foreground/[0.06] px-3 py-2 text-left text-[11.5px] text-foreground/40 transition-colors hover:bg-foreground/[0.03] hover:text-foreground/70"
                            >
                                Load older runs…
                            </button>
                        )}
                    </div>
                </TooltipProvider>
            )}
        </div>
    );
}

function PanelHeader({
    story,
    icons,
    switcher,
    onClose,
    builtinClose = false,
}: {
    story: RunStory;
    icons: RunVariantProps['icons'];
    switcher?: RunSwitcherData;
    onClose?: () => void;
    builtinClose?: boolean;
}) {
    return (
        <div
            className={cn(
                'flex shrink-0 items-start justify-between gap-3 border-b border-foreground/[0.06] px-5 py-4',
                builtinClose && 'pr-12'
            )}
        >
            <div className="min-w-0">
                <h2 className="m-0 truncate text-[15px] font-semibold tracking-tight text-foreground">
                    {story.workflowName}
                </h2>
                <div className="mt-1"><Verdict story={story} /></div>
            </div>
            <div className="flex shrink-0 items-center gap-2">
                {switcher && <RunSwitcher data={switcher} icons={icons} fallbackIso={story.startedAt} />}
                {!builtinClose && onClose && (
                    <button
                        type="button"
                        aria-label="Close"
                        onClick={onClose}
                        className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-foreground/[0.05] hover:text-foreground"
                    >
                        <X className="h-4 w-4" />
                    </button>
                )}
            </div>
        </div>
    );
}

function PanelFooter({ onDontShowAgain }: { onDontShowAgain?: () => void }) {
    return (
        <div className="flex shrink-0 items-center justify-between gap-3 border-t border-foreground/[0.06] px-5 py-2.5">
            <button
                type="button"
                onClick={onDontShowAgain}
                className="text-[12px] text-muted-foreground/70 transition-colors hover:text-muted-foreground"
            >
                Don&apos;t show again
            </button>
            <span className="text-[11px] text-muted-foreground/60">Re-enable in Settings</span>
        </div>
    );
}

/** Visible enough to find, quiet enough not to compete: a labelled text
    affordance — the word does the work a bare gear couldn't, without a boxed
    button outweighing the hairline eyebrow row it sits in. */
function ConfigButton({ nodeId, onOpenConfig }: { nodeId: string; onOpenConfig?: (id: string) => void }) {
    return (
        <button
            type="button"
            onClick={() => onOpenConfig?.(nodeId)}
            className="inline-flex shrink-0 items-center gap-1 rounded-md px-1 py-0.5 text-[11.5px] font-medium text-foreground/45 transition-colors hover:bg-foreground/[0.04] hover:text-foreground"
        >
            <Settings2 className="h-3 w-3" />
            Configure
        </button>
    );
}

/** The inspector: full row width with a clear gap below the row, so it reads
    as the row unfolding. Both halves render through the REAL output viewer
    (IODataDisplay), so tool args/results get the same JSON-tree/table modes
    as node outputs — one viewer everywhere. */
function TraceDetail({ row }: { row: ToolRow }) {
    return (
        <div className="mx-1 mb-1.5 mt-1 space-y-3 rounded-lg border border-foreground/[0.06] bg-foreground/[0.02] px-3.5 py-3">
            {row.args && <IODataDisplay data={row.args} label="Called with" />}
            {row.error ? (
                <div className="rounded-md border border-red-500/20 bg-red-500/[0.08] px-2.5 py-2 text-[11.5px] leading-relaxed text-red-700 dark:text-red-300">
                    {row.error}
                </div>
            ) : (
                row.result && <IODataDisplay data={row.result} label="Returned" />
            )}
        </div>
    );
}

/* --------------------------------------------------- trace: quiet log */

/** Each row answers three questions at a glance: did it work (leading zinc
    check — red ✗ is the only voice raised), what exactly it did (label + the
    call's salient argument in muted ink), and when/how long. */
function LogRow({ row, icons }: { row: StoryRow; icons: RunVariantProps['icons'] }) {
    const [open, setOpen] = useState(false);
    if (row.kind === 'thought') {
        return (
            <p className="m-0 px-2.5 py-1.5 text-[12.5px] italic leading-relaxed text-foreground/45">
                {row.text}
            </p>
        );
    }
    const failed = row.status === 'error';
    return (
        <div>
            <button
                type="button"
                onClick={() => setOpen((v) => !v)}
                className={cn(
                    'group flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left transition-colors hover:bg-foreground/[0.03]',
                    open && 'bg-foreground/[0.03]'
                )}
            >
                <span className="flex w-3.5 shrink-0 justify-center">
                    {failed ? (
                        <X className="h-3.5 w-3.5 text-red-500 dark:text-red-400" />
                    ) : (
                        <Check className="h-3.5 w-3.5 text-foreground/40" />
                    )}
                </span>
                <StepMark row={row} icons={icons} />
                <span className={cn('min-w-0 flex-1 truncate text-[13px]', failed ? 'text-foreground/85' : 'text-foreground/80')}>
                    {row.text}
                    {row.detail && (
                        <span className="text-foreground/40">{' · '}{row.detail}</span>
                    )}
                </span>
                {failed && (
                    <span className="shrink-0 text-[10px] font-medium uppercase tracking-[0.08em] text-red-500 dark:text-red-400">
                        failed
                    </span>
                )}
                {row.clock && (
                    <span className="shrink-0 font-mono text-[10.5px] tabular-nums text-foreground/25">
                        {row.clock}
                    </span>
                )}
                <span className="w-9 shrink-0 text-right font-mono text-[10.5px] tabular-nums text-foreground/35">
                    {sec(row.ms)}
                </span>
                <ChevronDown
                    className={cn(
                        'h-3 w-3 shrink-0 text-foreground/25 transition-all group-hover:text-foreground/70',
                        open && 'rotate-180'
                    )}
                />
            </button>
            {open && <TraceDetail row={row} />}
        </div>
    );
}

function LogTrace({ rows, icons }: { rows: StoryRow[]; icons: RunVariantProps['icons'] }) {
    return (
        <div className="px-1.5 py-1.5">
            {rows.map((r) => (
                <LogRow key={r.id} row={r} icons={icons} />
            ))}
        </div>
    );
}

/* -------------------------------------------------------- agent extras */

/** The agent's closing words — plain ink under a hairline, no icon box: the
    section header already names the agent, and the note should read as text,
    not another decorated row. */
function AgentNote({ response }: { response?: string }) {
    if (!response) return null;
    return (
        <div className="border-t border-foreground/[0.06] px-4 pb-3 pt-3">
            <MarkdownRenderer
                content={response}
                breaks
                className="text-[13px] leading-relaxed text-foreground/70"
            />
        </div>
    );
}

/** A failure carries its fix path with it: the backend-named action first
    (reconnect, top up), then a labelled Open config — the quiet section links
    are for the curious, this is for the person whose run just broke. */
function ErrorPanel({
    error,
    errorAction,
    nodeId,
    onOpenConfig,
}: {
    error?: string;
    errorAction?: ErrorAction;
    nodeId: string;
    onOpenConfig?: (id: string) => void;
}) {
    if (!error) return null;
    return (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3.5 py-3 text-[13px] leading-relaxed text-red-700 dark:text-red-300">
            {error}
            <div className="mt-3 flex flex-wrap items-center gap-2">
                {errorAction && <ErrorActionButton action={errorAction} nodeId={nodeId} />}
                <button
                    type="button"
                    onClick={() => onOpenConfig?.(nodeId)}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-foreground/15 px-3 py-1.5 text-xs font-semibold text-foreground/80 transition-colors hover:border-foreground/25 hover:bg-foreground/[0.05]"
                >
                    <Settings2 className="h-3.5 w-3.5" />
                    Open config
                </button>
            </div>
        </div>
    );
}

/* ---------------------------------------------------------------- sends */

/** One real send: a quiet destination line (where + when), then the app's own
    frame standing alone — the same treatment the inbound event gets, so cause
    and effect read as siblings. */
export function SentFrame({
    send,
    icons,
    agentName,
}: {
    send: StorySend;
    icons: RunVariantProps['icons'];
    agentName?: string;
}) {
    const artifact = {
        provider: send.provider,
        to: send.to,
        text: send.text ?? '',
        subject: send.subject,
        media: send.media,
    };
    const isEmail = isEmailShaped(artifact);
    return (
        <div>
            <div className="mb-1.5 flex items-center justify-between gap-3 px-0.5">
                <span className="inline-flex min-w-0 items-center gap-2">
                    <Glyph mark={icons[send.provider]} className="h-3.5 w-3.5 shrink-0" />
                    <span className="min-w-0 truncate text-[12px] font-medium text-foreground/60">
                        {send.to || 'Sent'}
                    </span>
                </span>
                <span className="inline-flex shrink-0 items-center gap-1.5 text-[11px] font-medium text-foreground/45">
                    <Check className="h-3 w-3 text-foreground/40" />
                    Sent{send.clock ? ` · ${send.clock}` : ''}
                </span>
            </div>
            <OutboundMessage
                icons={icons}
                artifact={artifact}
                hideDestination={!isEmail}
                agentName={agentName}
                suppressByline
            />
        </div>
    );
}

/** Done, and nothing went out — a real decision, reported in plain ink. */
function NothingWentOut({ response }: { response?: string }) {
    return (
        <div className={cn('px-4 py-4', SURFACE)}>
            <p className="m-0 flex items-center gap-2.5 text-[13.5px] font-medium text-foreground">
                <Check className="h-4 w-4 shrink-0 text-foreground/50" />
                Nothing went out
            </p>
            <MarkdownRenderer
                content={response ?? 'The agent decided nothing needed to be sent.'}
                className="mt-2 text-[12.5px] leading-relaxed text-foreground/55"
            />
        </div>
    );
}

/* ----------------------------------------------------------- supporting */

/** One supporting node, in the trace row's exact anatomy — leading status
    glyph, brand mark, label + salient output detail, expand — so "what the
    agent did" and "what else ran" read as one system, not two designs. */
function SupportingRow({
    node,
    icons,
    onOpenConfig,
    step,
}: {
    node: StoryNodeResult;
    icons: RunVariantProps['icons'];
    onOpenConfig?: (id: string) => void;
    /** 1-based step index — set when the list is the run's primary chain, so
        a deterministic sequence reads as 01 → 02, not two identical rows. */
    step?: number;
}) {
    const [open, setOpen] = useState(false);
    const failed = node.status === 'error';
    const skipped = node.status === 'skipped';
    const detail = deriveNodeDetail(node.output);
    const hasOutput = node.output !== undefined && node.output !== null;
    return (
        <div>
            <div
                className={cn(
                    'flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 transition-colors hover:bg-foreground/[0.03]',
                    open && 'bg-foreground/[0.03]'
                )}
            >
                <button
                    type="button"
                    onClick={() => setOpen((v) => !v)}
                    className="group flex min-w-0 flex-1 items-center gap-2.5 text-left"
                >
                    {step !== undefined && (
                        <span className="w-5 shrink-0 text-right font-mono text-[10.5px] tabular-nums text-foreground/25">
                            {String(step).padStart(2, '0')}
                        </span>
                    )}
                    <span className="flex w-3.5 shrink-0 justify-center">
                        {failed ? (
                            <X className="h-3.5 w-3.5 text-red-500 dark:text-red-400" />
                        ) : skipped ? (
                            <Minus className="h-3.5 w-3.5 text-foreground/25" />
                        ) : (
                            <Check className="h-3.5 w-3.5 text-foreground/40" />
                        )}
                    </span>
                    <NodeMark slug={node.nodeType} icons={icons} className="h-3.5 w-3.5 shrink-0" />
                    <span
                        className={cn(
                            'min-w-0 flex-1 truncate text-[13px]',
                            skipped ? 'text-foreground/45' : 'text-foreground/80'
                        )}
                    >
                        {node.label}
                        {detail && !skipped && (
                            <span className="text-foreground/40">{' · '}{detail}</span>
                        )}
                    </span>
                    {failed && (
                        <span className="shrink-0 text-[10px] font-medium uppercase tracking-[0.08em] text-red-500 dark:text-red-400">
                            failed
                        </span>
                    )}
                    {skipped && (
                        <span className="shrink-0 text-[10px] font-medium uppercase tracking-[0.08em] text-foreground/30">
                            skipped
                        </span>
                    )}
                    <ChevronDown
                        className={cn(
                            'h-3 w-3 shrink-0 text-foreground/25 transition-all group-hover:text-foreground/70',
                            open && 'rotate-180'
                        )}
                    />
                </button>
                <ConfigButton nodeId={node.nodeId} onOpenConfig={onOpenConfig} />
            </div>
            {open && (
                <div className="mx-1 mb-1.5 mt-1 rounded-lg border border-foreground/[0.06] bg-foreground/[0.02] px-3.5 py-3">
                    {node.error ? (
                        <ErrorPanel
                            error={node.error}
                            errorAction={node.errorAction}
                            nodeId={node.nodeId}
                            onOpenConfig={onOpenConfig}
                        />
                    ) : hasOutput ? (
                        <IODataDisplay data={node.output} label="Output" nodeId={node.nodeId} />
                    ) : (
                        <p className="m-0 text-[12.5px] text-foreground/40">
                            {skipped ? 'This node was skipped.' : 'No output.'}
                        </p>
                    )}
                </div>
            )}
        </div>
    );
}

/** The trigger identity row: mark + node name + when the event landed. */
export function TriggerIdentity({ story, icons }: { story: RunStory; icons: RunVariantProps['icons'] }) {
    const t = story.trigger;
    if (!t) return null;
    return (
        <span className="inline-flex min-w-0 items-center gap-2">
            <NodeMark slug={t.slug} icons={icons} className="h-3.5 w-3.5 shrink-0" fallback="bolt" />
            <span className="truncate text-[12px] font-medium text-foreground/60">{t.label}</span>
            {(t.scenario?.lead.time ?? t.bare?.time) && (
                <span className="font-mono text-[10.5px] text-foreground/30">
                    {t.scenario?.lead.time ?? t.bare?.time}
                </span>
            )}
        </span>
    );
}

/** The inbound event. A themed payload wears its app's own frame BARE — the
    AppSurface is already a card, and boxing it again double-framed the thing
    we most want to feel real. Unthemed leads and raw events keep the quiet
    card. */
export function InboundCard({ story }: { story: RunStory }) {
    const t = story.trigger;
    if (!t) return null;
    if (t.scenario) {
        if (resolveAppTheme(t.slug)) return <InboundMessage scenario={t.scenario} />;
        return (
            <div className={cn('px-4 py-3.5', SURFACE)}>
                <InboundMessage scenario={t.scenario} />
            </div>
        );
    }
    // A schedule tick has no content — one quiet line, not an id dump.
    if (t.bare) {
        const scheduled = /cron|schedule/.test(t.slug);
        return (
            <p className={cn('m-0 flex items-center gap-2.5 px-4 py-3 text-[13px] text-foreground/70', SURFACE)}>
                <Clock className="h-4 w-4 shrink-0 text-foreground/40" />
                {scheduled ? 'Ran on schedule' : 'Trigger fired'}
                {t.bare.time && (
                    <span className="font-mono text-[11px] text-foreground/35">{t.bare.time}</span>
                )}
            </p>
        );
    }
    // Unrecognised payload: the SANITIZED event — the delivery envelope's
    // internal ids and _webhook plumbing never reach the reader.
    return (
        <div className={cn('px-4 py-3.5', SURFACE)}>
            <IODataDisplay data={t.event ?? {}} label="Event" nodeId={t.nodeId} />
        </div>
    );
}

/** The reply of a bare chat turn, given top billing — for a run with no
    trigger and no tool calls, this IS the outcome, not a footnote under a
    "Nothing went out" verdict it never earned. */
function AgentReply({ response }: { response?: string }) {
    return (
        <div className={cn('px-4 py-4', SURFACE)}>
            <MarkdownRenderer
                content={response ?? ''}
                breaks
                className="text-[13.5px] leading-relaxed text-foreground/90"
            />
        </div>
    );
}

/** A provider-wired tool node: it equipped the agent, it didn't "run" — so
    no status check, a wrench, and the toolkit it granted in plain words
    instead of the internal provider envelope. */
function ProviderRow({
    provider,
    icons,
    onOpenConfig,
}: {
    provider: StoryToolProvider;
    icons: RunVariantProps['icons'];
    onOpenConfig?: (id: string) => void;
}) {
    const [open, setOpen] = useState(false);
    const n = provider.operations.length;
    return (
        <div>
            <div
                className={cn(
                    'flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 transition-colors hover:bg-foreground/[0.03]',
                    open && 'bg-foreground/[0.03]'
                )}
            >
                <button
                    type="button"
                    onClick={() => setOpen((v) => !v)}
                    className="group flex min-w-0 flex-1 items-center gap-2.5 text-left"
                >
                    <span className="flex w-3.5 shrink-0 justify-center">
                        <Wrench className="h-3.5 w-3.5 text-foreground/30" />
                    </span>
                    <NodeMark slug={provider.nodeType} icons={icons} className="h-3.5 w-3.5 shrink-0" />
                    <span className="min-w-0 flex-1 truncate text-[13px] text-foreground/80">
                        {provider.label}
                        <span className="text-foreground/40">
                            {' · '}
                            {n === 0 ? 'no tools allowlisted' : `${n} tool${n === 1 ? '' : 's'}`}
                        </span>
                    </span>
                    <ChevronDown
                        className={cn(
                            'h-3 w-3 shrink-0 text-foreground/25 transition-all group-hover:text-foreground/70',
                            open && 'rotate-180'
                        )}
                    />
                </button>
                <ConfigButton nodeId={provider.nodeId} onOpenConfig={onOpenConfig} />
            </div>
            {open && (
                <div className="mx-1 mb-1.5 mt-1 rounded-lg border border-foreground/[0.06] bg-foreground/[0.02] px-3.5 py-3">
                    {n > 0 ? (
                        <ul className="m-0 list-none space-y-1 p-0">
                            {provider.operations.map((op) => (
                                <li key={op} className="flex items-center gap-2 text-[12.5px] text-foreground/70">
                                    <span className="h-1 w-1 shrink-0 rounded-full bg-foreground/30" />
                                    {humanizeOp(op)}
                                </li>
                            ))}
                        </ul>
                    ) : (
                        <p className="m-0 text-[12.5px] text-foreground/40">
                            No operations allowlisted — the agent had no tools from this node.
                        </p>
                    )}
                    {provider.credentialLabel && (
                        <p className="m-0 mt-2 text-[11.5px] text-foreground/40">
                            Using {provider.credentialLabel}
                        </p>
                    )}
                </div>
            )}
        </div>
    );
}

/* ================================================================ story */

export function StoryVariant({
    story,
    icons,
    onOpenConfig,
    onClose,
    switcher,
    onDontShowAgain,
    builtinClose,
}: RunVariantProps) {
    const { trigger, agent, providers, supporting } = story;
    const failed = agent?.status === 'error';
    const outcome = outcomeModeFor(story);
    // The agent's closing words appear ONCE: in the trace card when the
    // outcome section carries sends or an error, in the outcome card when it
    // carries the reply or restraint.
    const showNote = outcome === 'sends' || outcome === 'error';
    return (
        <div className="flex h-full min-h-0 flex-col">
            <PanelHeader
                story={story}
                icons={icons}
                switcher={switcher}
                onClose={onClose}
                builtinClose={builtinClose}
            />
            <div className="scrollbar-subtle min-h-0 flex-1 space-y-6 overflow-y-auto px-6 py-5">
                {trigger && (
                    <section>
                        <Eyebrow
                            right={
                                <span className="flex items-center gap-1.5">
                                    <TriggerIdentity story={story} icons={icons} />
                                    <ConfigButton nodeId={trigger.nodeId} onOpenConfig={onOpenConfig} />
                                </span>
                            }
                        >
                            What came in
                        </Eyebrow>
                        <InboundCard story={story} />
                    </section>
                )}

                {agent && (
                    <section>
                        <Eyebrow
                            right={
                                <span className="flex items-center gap-1.5">
                                    <span className="inline-flex items-center gap-2">
                                        <NodeMark slug="agent" icons={icons} className="h-3.5 w-3.5" />
                                        <span className="text-[12px] font-medium text-foreground/60">{agent.label}</span>
                                    </span>
                                    <ConfigButton nodeId={agent.nodeId} onOpenConfig={onOpenConfig} />
                                </span>
                            }
                        >
                            What the agent did
                        </Eyebrow>
                        <div className={SURFACE}>
                            {agent.rows.length > 0 ? (
                                <LogTrace rows={agent.rows} icons={icons} />
                            ) : (
                                <p className="m-0 px-3.5 py-2.5 text-[12.5px] text-foreground/40">
                                    The agent made no tool calls this run.
                                </p>
                            )}
                            {showNote && <AgentNote response={agent.response} />}
                        </div>
                        {failed && (
                            <div className="mt-3">
                                <ErrorPanel
                                    error={agent.error}
                                    errorAction={agent.errorAction}
                                    nodeId={agent.nodeId}
                                    onOpenConfig={onOpenConfig}
                                />
                            </div>
                        )}
                    </section>
                )}

                {/* A failed run earned no outcome verdict — the error owns the story. */}
                {agent && outcome === 'sends' && (
                    <section>
                        <Eyebrow>What went out ({agent.sends.length})</Eyebrow>
                        <div className="space-y-4">
                            {agent.sends.map((s, i) => (
                                <SentFrame key={i} send={s} icons={icons} agentName={story.agentName} />
                            ))}
                        </div>
                    </section>
                )}
                {agent && outcome === 'reply' && (
                    <section>
                        <Eyebrow>Agent&apos;s reply</Eyebrow>
                        <AgentReply response={agent.response} />
                    </section>
                )}
                {agent && outcome === 'restraint' && (
                    <section>
                        <Eyebrow>Outcome</Eyebrow>
                        <NothingWentOut response={agent.response} />
                    </section>
                )}

                {supporting.length > 0 && (
                    <section>
                        <Eyebrow>{agent ? `Also ran (${supporting.length})` : 'What ran'}</Eyebrow>
                        <div className={cn('px-1.5 py-1.5', SURFACE)}>
                            {supporting.map((n, i) => (
                                <SupportingRow
                                    key={n.nodeId}
                                    node={n}
                                    icons={icons}
                                    onOpenConfig={onOpenConfig}
                                    // A deterministic chain is a SEQUENCE — number
                                    // the steps so two "Delay" rows read as 01 → 02.
                                    step={agent ? undefined : i + 1}
                                />
                            ))}
                        </div>
                    </section>
                )}

                {providers.length > 0 && (
                    <section>
                        <Eyebrow>Agent&apos;s toolkit ({providers.length})</Eyebrow>
                        <div className={cn('px-1.5 py-1.5', SURFACE)}>
                            {providers.map((pr) => (
                                <ProviderRow key={pr.nodeId} provider={pr} icons={icons} onOpenConfig={onOpenConfig} />
                            ))}
                        </div>
                    </section>
                )}
            </div>
            <PanelFooter onDontShowAgain={onDontShowAgain} />
        </div>
    );
}

/* ------------------------------------------------------------- exports */

/** Every mark the story renders — node types (rows), provider slugs (trace,
    sends, trigger frame) — resolved from the client icon registry and keyed
    under BOTH spellings. Callers memoize per story. */
export function buildStoryIcons(story: RunStory): Record<string, Mark> {
    const keys = new Set<string>(['agent']);
    if (story.trigger) keys.add(story.trigger.slug);
    for (const n of story.supporting) keys.add(n.nodeType);
    for (const row of story.agent?.rows ?? []) {
        if (row.kind === 'tool' && row.provider) keys.add(row.provider);
    }
    for (const s of story.agent?.sends ?? []) keys.add(s.provider);
    const icons: Record<string, Mark> = {};
    for (const key of keys) {
        for (const type of [key, `automation-${key.replace(/_/g, '-')}`]) {
            const meta = getNodeIconMeta(type);
            if (meta?.iconHtml) {
                const mark = { iconHtml: meta.iconHtml, iconColor: meta.iconColor };
                icons[key] = mark;
                icons[slugOfType(key)] = mark;
                break;
            }
        }
    }
    return icons;
}

/** Memoized icon map for one story. */
export function useStoryIcons(story: RunStory): Record<string, Mark> {
    return useMemo(() => buildStoryIcons(story), [story]);
}
