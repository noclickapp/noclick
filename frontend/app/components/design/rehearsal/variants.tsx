/* Four views of the same rehearsal, all driven by the captured fixtures, so the
   choice between them is about how the run READS. Every tool row opens into the
   same inspector — the call the agent actually made and what the stand-in world
   answered — and thought rows sit inline where they happened, because "exactly
   what it did" includes why. The honesty furniture (stand-in marker, "not
   sent") is shared and not up for redesign. */

import { useState } from 'react';
import { Check, ChevronDown, FlaskConical, Globe, Loader2, Pencil, Play, Plug, Terminal, X, Zap } from 'lucide-react';
import { MarkdownRenderer } from '~/components/chat/MarkdownRendererLazy';
import { SerializedIcon } from '~/components/shared/SerializedIcon';
import { ThinkingOrb } from '~/components/shared/ThinkingOrb';
import { CARD } from '~/lib/cardStyles';
import { cn } from '~/lib/utils';
import { AGENT_NAME, type Provider, type Scenario, type TriggerFixture } from './fixture';
import { InboundMessage, OutboundMessage, isEmailShaped, type LeadPatch } from './native';
import type { ReplayRow, ReplayState } from './useReplay';

export interface Mark {
    iconHtml?: string;
    iconColor?: string;
    /** Client-side alternative: a ready icon node (the workspace registry's
        Icon components), for hosts with no server loader. */
    node?: React.ReactNode;
}
export interface VariantProps {
    run: ReplayState;
    scenario: Scenario;
    /** Marks keyed by the backend's tool-name prefix (provider slug) plus
        'agent'. Open-keyed: any wired provider can appear in a live trace. */
    icons: Record<string, Mark>;
    /** Editing the staged message, owned by the route so edits survive view
        switches. */
    editing: boolean;
    onToggleEdit: () => void;
    onPatch: (patch: LeadPatch) => void;
    /** Which tool-call row treatment the bench is showing. */
    traceStyle: TraceStyle;
    /** Every trigger, for switching the node type at the message itself. */
    triggers: TriggerFixture[];
    onTrigger: (slug: string) => void;
}

const sec = (ms: number) => `${(ms / 1000).toFixed(1)}s`;

/** The mark for a tool row: the provider's own icon when the call went through
    an account, a generic mark (web / MCP plug / terminal) when it did not.
    Every tool the product can dispatch renders as SOMETHING — an iconless row
    reads as broken. */
function StepMark({
    row,
    icons,
    className = 'h-3.5 w-3.5 shrink-0',
}: {
    row: Extract<ReplayRow, { kind: 'tool' }>;
    icons: VariantProps['icons'];
    className?: string;
}) {
    // Provider slug first; a slug with no registered mark (platform tools,
    // label-derived duplicate slugs) falls through to the generic glyph rather
    // than rendering nothing.
    const mark = row.provider ? icons[row.provider] : undefined;
    if (mark?.node || mark?.iconHtml) return <Glyph mark={mark} className={className} />;
    const Generic =
        row.glyph === 'terminal' ? Terminal : row.glyph === 'globe' ? Globe : Plug;
    return <Generic className={cn(className, 'text-foreground/45')} />;
}

function StandIn() {
    return (
        <span className="inline-flex items-center gap-1.5 text-[11px] text-foreground/40">
            <FlaskConical className="h-3 w-3" /> stand-in data
        </span>
    );
}

/** Per-row honesty: every tool call in a rehearsal was answered by the
    fabricated world, and each row says so itself — a section-level chip
    scrolls away, but the row travels with its screenshot. "Simulated", not
    "mocked": non-technical users know simulations; "mocked" reads as jargon
    or worse, mockery (2026-08-10 request). */
function MockedPill() {
    return (
        <span
            title="Answered with simulated data — no real call was made"
            // leading-none: at 9.5px uppercase the default line box rides the
            // text below optical center inside the bordered pill.
            className="inline-flex shrink-0 items-center gap-1 rounded border border-foreground/10 px-1.5 py-[2px] text-[9.5px] font-medium uppercase leading-none tracking-[0.08em] text-foreground/30"
        >
            <FlaskConical className="h-2.5 w-2.5" /> simulated
        </span>
    );
}

/** The mark for a trigger identity: its provider icon, or the amber bolt —
    the same mark real triggers carry on the canvas — when it has none. */
function TriggerMark({
    provider,
    icons,
    className = 'h-4 w-4 shrink-0',
}: {
    /** Provider or icon slug — any key into the marks map. */
    provider: string;
    icons: VariantProps['icons'];
    className?: string;
}) {
    const mark = provider === 'generic' ? undefined : icons[provider];
    if (mark?.node || mark?.iconHtml) return <Glyph mark={mark} className={className} />;
    return (
        <Zap
            className={cn(className, 'text-amber-600 dark:text-amber-400')}
            fill="currentColor"
        />
    );
}

function Glyph({ mark, className }: { mark?: Mark; className?: string }) {
    if (mark?.node) return <span className={cn('inline-flex', className)}>{mark.node}</span>;
    if (!mark?.iconHtml) return null;
    return (
        <SerializedIcon html={mark.iconHtml} iconColor={mark.iconColor} className={className} />
    );
}

/* ------------------------------------------------------------ inspector */

/** JSON with just enough tint to scan: keys and punctuation recede, values
    carry the information. Two tones of the same ink — the page's colour budget
    is already spent (amber bolt, emerald checks, sky mentions). */
function JsonBlock({
    label,
    value,
    standIn = false,
}: {
    label: string;
    value: unknown;
    standIn?: boolean;
}) {
    const text = JSON.stringify(value, null, 2) ?? '';
    const nodes: React.ReactNode[] = [];
    const re =
        /("(?:[^"\\]|\\.)*")(\s*:)?|\b(?:true|false|null)\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/g;
    let last = 0;
    let k = 0;
    let m: RegExpExecArray | null;
    while ((m = re.exec(text))) {
        if (m.index > last) {
            nodes.push(
                <span key={k++} className="text-foreground/30">
                    {text.slice(last, m.index)}
                </span>
            );
        }
        if (m[1] && m[2]) {
            nodes.push(
                <span key={k++} className="text-foreground/45">
                    {m[1]}
                    {m[2]}
                </span>
            );
        } else {
            nodes.push(
                <span key={k++} className="text-foreground/80">
                    {m[0]}
                </span>
            );
        }
        last = re.lastIndex;
    }
    if (last < text.length) {
        nodes.push(
            <span key={k++} className="text-foreground/30">
                {text.slice(last)}
            </span>
        );
    }
    return (
        <div className="min-w-0">
            <p className="m-0 mb-1.5 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.1em] text-foreground/30">
                {label}
                {standIn && <FlaskConical className="h-2.5 w-2.5" />}
            </p>
            <pre className="scrollbar-subtle m-0 max-h-[200px] overflow-auto font-mono text-[11px] leading-relaxed">
                {nodes}
            </pre>
        </div>
    );
}

/** The call and the answer, exactly as they happened. Arguments are the half
    the agent authored; the result is the fabricated half and says so. One
    inset panel, aligned under the row's text, so the detail reads as the row
    unfolding rather than a new component arriving. */
function ToolDetail({
    row,
    dense = false,
    frame = 'panel',
}: {
    row: Extract<ReplayRow, { kind: 'tool' }>;
    dense?: boolean;
    frame?: 'panel' | 'flush' | 'bare';
}) {
    const blocks = (
        <>
            <JsonBlock label="Called with" value={row.args} />
            {row.result && <JsonBlock label="Returned · stand-in" value={row.result} standIn />}
        </>
    );
    if (frame === 'flush') {
        return <div className="space-y-3 border-t border-foreground/8 px-3 py-2.5">{blocks}</div>;
    }
    if (frame === 'bare') {
        return <div className="mb-2 space-y-3 pl-10 pr-4">{blocks}</div>;
    }
    return (
        <div
            className={cn(
                'mb-2 space-y-3 rounded-lg border border-foreground/8 bg-foreground/[0.02] px-3 py-2.5',
                dense ? 'ml-6 mr-0' : 'ml-10 mr-4'
            )}
        >
            {blocks}
        </div>
    );
}

export type TraceStyle = 'rail' | 'chips' | 'console' | 'cards';

/** One row of the trace, in one of four stances. Rail threads a sequence;
    chips read as the agent reaching for things; console is the honest ledger;
    cards give every call its own weight. Same data, same inspector — the
    choice is about how much ceremony a tool call deserves. */
function TraceRow({
    row,
    icons,
    dense = false,
    styleVariant = 'rail',
}: {
    row: ReplayRow;
    icons: VariantProps['icons'];
    dense?: boolean;
    styleVariant?: TraceStyle;
}) {
    const [open, setOpen] = useState(false);

    if (row.kind === 'thought') {
        if (styleVariant === 'console') {
            return (
                <p
                    className={cn(
                        'm-0 py-1 font-mono text-[11.5px] leading-relaxed text-foreground/35',
                        dense ? 'px-0' : 'px-4'
                    )}
                >
                    <span className="select-none text-foreground/25"># </span>
                    {row.text}
                </p>
            );
        }
        return (
            <div
                className={cn(
                    'flex items-start gap-2.5',
                    dense ? 'px-0 py-1.5' : 'px-4 py-2'
                )}
            >
                {styleVariant === 'rail' ? (
                    <span className="flex w-3.5 shrink-0 justify-center pt-[7px]">
                        <span className="h-1 w-1 rounded-full bg-foreground/30" />
                    </span>
                ) : null}
                <p className="m-0 min-w-0 flex-1 text-[12.5px] italic leading-relaxed text-foreground/45">
                    {row.text}
                </p>
            </div>
        );
    }

    const time =
        row.status === 'completed' && row.ms != null ? sec(row.ms) : sec(row.elapsed);
    const status =
        row.status === 'completed' ? (
            <Check className="h-3.5 w-3.5 text-emerald-400" />
        ) : row.status === 'error' ? (
            <X className="h-3.5 w-3.5 text-red-400" />
        ) : (
            <Loader2 className="h-3.5 w-3.5 animate-spin text-foreground/40" />
        );

    if (styleVariant === 'chips') {
        return (
            <div className={cn(dense ? 'px-0 py-1' : 'px-4 py-1.5')}>
                <button
                    onClick={() => setOpen((v) => !v)}
                    className={cn(
                        'group inline-flex max-w-full items-center gap-2 rounded-full border py-1 pl-2 pr-2.5 text-left transition-colors',
                        open
                            ? 'border-foreground/25 bg-foreground/[0.05]'
                            : 'border-foreground/10 bg-foreground/[0.02] hover:border-foreground/20'
                    )}
                >
                    <span className="flex h-3.5 w-3.5 shrink-0 items-center justify-center">
                        {status}
                    </span>
                    <StepMark row={row} icons={icons} />
                    <span className="min-w-0 truncate text-[12.5px] text-foreground/85">
                        {row.text}
                    </span>
                    <MockedPill />
                    <span className="shrink-0 font-mono text-[10.5px] tabular-nums text-foreground/30">
                        {time}
                    </span>
                    <ChevronDown
                        className={cn(
                            'h-3 w-3 shrink-0 text-foreground/25 transition-all group-hover:text-foreground/70',
                            open && 'rotate-180'
                        )}
                    />
                </button>
                {open && <ToolDetail row={row} dense={dense} />}
            </div>
        );
    }

    if (styleVariant === 'console') {
        const slug = `${row.provider ?? row.glyph ?? 'tool'}.${row.text.toLowerCase().replace(/ /g, '_')}`;
        return (
            <div>
                <button
                    onClick={() => setOpen((v) => !v)}
                    className={cn(
                        'group flex w-full items-center gap-2 py-1 text-left font-mono text-[12px] transition-colors hover:bg-foreground/[0.03]',
                        dense ? 'px-0' : 'px-4'
                    )}
                >
                    <span
                        className={cn(
                            'w-3 shrink-0 select-none',
                            row.status === 'completed'
                                ? 'text-emerald-400'
                                : row.status === 'error'
                                  ? 'text-red-400'
                                  : 'animate-pulse text-foreground/40'
                        )}
                    >
                        {row.status === 'completed' ? '✓' : row.status === 'error' ? '✗' : '…'}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-foreground/80">{slug}</span>
                    {/* console keeps its mono idiom — a bracket tag, not a pill */}
                    <span className="shrink-0 select-none text-foreground/25">[mock]</span>
                    <span className="shrink-0 tabular-nums text-foreground/30">({time})</span>
                    <ChevronDown
                        className={cn(
                            'h-3 w-3 shrink-0 text-foreground/25 transition-all group-hover:text-foreground/70',
                            open && 'rotate-180'
                        )}
                    />
                </button>
                {open && <ToolDetail row={row} dense={dense} frame="bare" />}
            </div>
        );
    }

    if (styleVariant === 'cards') {
        const expandable = row.args != null;
        return (
            <div className={cn(dense ? 'px-0 py-1' : 'px-4 py-1.5')}>
                <div className="overflow-hidden rounded-lg border border-foreground/10">
                    <button
                        disabled={!expandable}
                        onClick={() => setOpen((v) => !v)}
                        className="group flex w-full items-center gap-2.5 bg-foreground/[0.02] px-3 py-2 text-left transition-colors hover:bg-foreground/[0.04]"
                    >
                        <span className="flex w-3.5 shrink-0 justify-center">{status}</span>
                        <StepMark row={row} icons={icons} />
                        <span className="min-w-0 flex-1 truncate text-[13px] text-foreground/85">
                            {row.text}
                        </span>
                        <MockedPill />
                        <span className="shrink-0 font-mono text-[11px] tabular-nums text-foreground/30">
                            {time}
                        </span>
                        {expandable && (
                            <ChevronDown
                                className={cn(
                                    'h-3 w-3 shrink-0 text-foreground/25 transition-all group-hover:text-foreground/70',
                                    open && 'rotate-180'
                                )}
                            />
                        )}
                    </button>
                    {open && expandable && <ToolDetail row={row} frame="flush" />}
                </div>
            </div>
        );
    }

    return (
        <div>
            <button
                onClick={() => setOpen((v) => !v)}
                className={cn(
                    'group flex w-full items-center gap-2.5 rounded-lg text-left transition-colors hover:bg-foreground/[0.03]',
                    dense ? 'px-0 py-1.5' : 'px-4 py-2'
                )}
            >
                <span className="flex w-3.5 shrink-0 justify-center">{status}</span>
                <StepMark row={row} icons={icons} />
                <span className="min-w-0 flex-1 truncate text-[13px] text-foreground/85">
                    {row.text}
                </span>
                <MockedPill />
                <span className="shrink-0 font-mono text-[11px] tabular-nums text-foreground/30">
                    {time}
                </span>
                <ChevronDown
                    className={cn(
                        'h-3 w-3 shrink-0 text-foreground/25 transition-all group-hover:text-foreground/70',
                        open && 'rotate-180'
                    )}
                />
            </button>
            {open && <ToolDetail row={row} dense={dense} />}
        </div>
    );
}

function Placeholder({ dense = false }: { dense?: boolean }) {
    return (
        <div
            className={cn(
                'flex items-center gap-2.5 text-[13px] text-foreground/45',
                dense ? 'px-0 py-2' : 'px-4 py-3'
            )}
        >
            <span className="flex w-4 shrink-0 justify-center">
                <ThinkingOrb size={20} style={{ width: 16, height: 16 }} />
            </span>
            {/* No clock and no ellipsis: the orb already says "in motion", and
                a ticking counter promises precision thinking doesn't have. */}
            <span className="min-w-0 flex-1">Thinking</span>
        </div>
    );
}

/** The trace as one sequence: a hairline rail threads the markers together, so
    thought → call → thought → call reads as a single narrative instead of rows
    adrift in the void. */
export function Trace({
    rows,
    icons,
    dense = false,
    styleVariant = 'rail',
    running = false,
    className,
}: {
    rows: ReplayRow[];
    icons: VariantProps['icons'];
    dense?: boolean;
    styleVariant?: TraceStyle;
    /** The placeholder is a promise of activity — it may only exist while the
        run is actually running. A finished run with no tool calls shows an
        empty trace, and the outcome below carries the story. */
    running?: boolean;
    className?: string;
}) {
    return (
        <div className={cn('relative', className)}>
            {styleVariant === 'rail' && (
                <span
                    aria-hidden
                    className={cn(
                        'pointer-events-none absolute bottom-3 top-3 w-px bg-foreground/[0.07]',
                        dense ? 'left-[6px]' : 'left-[22px]'
                    )}
                />
            )}
            {rows.map((r) => (
                <TraceRow
                    key={r.id}
                    row={r}
                    icons={icons}
                    dense={dense}
                    styleVariant={styleVariant}
                />
            ))}
            {/* The promise of activity holds through EVERY gap while the run
                is live — before the first call AND between calls (a completed
                row followed by silence read as a stall, 2026-08-10). It may
                only exist while the run is actually running: a finished run
                with no tool calls shows an empty trace, and the outcome
                carries the story. */}
            {running &&
                !rows.some((r) => r.kind === 'tool' && r.status === 'in_progress') && (
                    <Placeholder dense={dense} />
                )}
        </div>
    );
}


/** Which node type the staged message arrives through — the circle logo and
    the type's catalog name ("Gmail"), sitting ABOVE the message it produces.
    Switching here switches the whole staged world to that trigger. */
function NodeTypeDropdown({
    triggers,
    current,
    onTrigger,
    icons,
}: {
    triggers: TriggerFixture[];
    current: TriggerFixture['slug'];
    onTrigger: (slug: string) => void;
    icons: VariantProps['icons'];
}) {
    const [open, setOpen] = useState(false);
    const active = triggers.find((t) => t.slug === current) ?? triggers[0];
    // One trigger is a fact, not a choice — render it as a label. A dropdown
    // with a single option reads as a control pretending to be one.
    if (triggers.length <= 1) {
        return (
            <span className="-ml-1 flex items-center gap-2.5 px-2 py-1.5">
                <TriggerMark provider={active.iconSlug ?? active.provider} icons={icons} />
                <span className="text-[13.5px] font-medium">{active.nodeName}</span>
            </span>
        );
    }
    return (
        <div className="relative inline-block">
            <button
                onClick={() => setOpen((v) => !v)}
                className="group -ml-1 flex items-center gap-2.5 rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-foreground/[0.04]"
            >
                <TriggerMark provider={active.iconSlug ?? active.provider} icons={icons} />
                <span className="text-[13.5px] font-medium">{active.nodeName}</span>
                <ChevronDown
                    className={cn(
                        'h-3.5 w-3.5 shrink-0 text-foreground/35 transition-colors group-hover:text-foreground/80',
                        open && 'rotate-180'
                    )}
                />
            </button>
            {open && (
                <>
                    <button
                        aria-label="Close"
                        onClick={() => setOpen(false)}
                        className="fixed inset-0 z-10 cursor-default"
                    />
                    <div className="absolute z-20 mt-1.5 w-[220px] overflow-hidden rounded-xl border border-border bg-popover/95 shadow-2xl backdrop-blur-md dark:bg-zinc-950/95">
                        {triggers.map((t) => {
                            const sel = t.slug === current;
                            return (
                                <button
                                    key={t.slug}
                                    onClick={() => {
                                        onTrigger(t.slug);
                                        setOpen(false);
                                    }}
                                    className={cn(
                                        'flex w-full items-center gap-2.5 px-3 py-2 text-left transition-colors',
                                        sel ? 'bg-foreground/[0.06]' : 'hover:bg-foreground/[0.03]'
                                    )}
                                >
                                    <TriggerMark provider={t.iconSlug ?? t.provider} icons={icons} />
                                    <span
                                        className={cn(
                                            'min-w-0 flex-1 truncate text-[12.5px]',
                                            sel ? 'font-medium text-foreground' : 'text-foreground/65'
                                        )}
                                    >
                                        {t.nodeName}
                                    </span>
                                </button>
                            );
                        })}
                    </div>
                </>
            )}
        </div>
    );
}

/** Edit in, Save out. No reset: an edit is the builder's staged message now —
    permanent until they edit it again. */
function EditControls({
    editing,
    onToggleEdit,
    disabled,
}: {
    editing: boolean;
    onToggleEdit: () => void;
    disabled?: boolean;
}) {
    return (
        <span className="flex items-center gap-0.5">
            <button
                onClick={onToggleEdit}
                disabled={disabled}
                title={editing ? 'Done editing' : 'Edit the staged message'}
                className={cn(
                    'flex items-center gap-1.5 rounded-md px-2 py-1.5 text-[12px] font-medium transition-colors disabled:opacity-40',
                    editing
                        ? 'bg-foreground/[0.06] text-foreground'
                        : 'text-foreground/35 hover:bg-foreground/[0.04] hover:text-foreground/80'
                )}
            >
                {editing ? <Check className="h-3.5 w-3.5" /> : <Pencil className="h-3 w-3" />}
                {editing ? 'Save' : 'Edit'}
            </button>
        </span>
    );
}

/** The run action, on the thing it runs. White (primary) because it is the
    page's one true action; everything else is chrome. */
function RunTest({ run }: { run: ReplayState }) {
    const running = run.phase === 'running';
    return (
        <button
            onClick={run.phase === 'idle' ? run.start : run.replay}
            disabled={running}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-[12px] font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-50"
        >
            {running ? (
                <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
                <Play className="h-3 w-3" />
            )}
            Test Run
        </button>
    );
}

function OutcomeEyebrow({ sent }: { sent: boolean }) {
    return (
        <div className="mb-2 flex items-baseline justify-between gap-3 px-0.5">
            <span className="text-[11px] font-semibold uppercase tracking-[0.1em] text-foreground/35">
                {sent ? 'What it would have sent' : 'Outcome'}
            </span>
            <span className="flex items-center gap-1.5 text-[11px] text-foreground/35">
                <FlaskConical className="h-3 w-3" /> {sent ? 'not sent' : 'nothing sent'}
            </span>
        </div>
    );
}

/** A hairline of the destination app: glyph + where. */
function DestinationBar({
    icons,
    artifact,
}: {
    icons: VariantProps['icons'];
    artifact: NonNullable<ReplayState['artifacts']>[number];
}) {
    return (
        <div className="flex items-center gap-2 border-b border-foreground/8 bg-[#121216] px-3.5 py-2">
            <Glyph mark={icons[artifact.provider]} className="h-3.5 w-3.5" />
            <span className="min-w-0 truncate text-[12.5px] font-medium text-foreground/70">
                {artifact.to}
            </span>
        </div>
    );
}

/** The payoff as the destination would show it — four takes on how much of
    that destination to bring along. The trace above stays uniform and quiet;
    this is the one thing the run exists to produce. */
export function Outcome({
    run,
    scenario,
    icons,
}: {
    run: ReplayState;
    scenario: Scenario;
    icons: VariantProps['icons'];
}) {
    const artifacts = run.artifacts;

    // A failed run with nothing sent gets NO outcome — "Nothing to send ✓"
    // next to a red error panel reads as a verdict the run never earned.
    // Artifacts still show on failure: what it composed before breaking is
    // honest and useful.
    if (!artifacts?.length && run.failed) return null;

    // Restraint has no destination to frame — the elevated panel carries it in
    // every stance, with equal ceremony.
    if (!artifacts?.length) {
        return (
            <div className="mt-6">
                <OutcomeEyebrow sent={false} />
                <div className="rounded-xl border border-[#26262c] bg-[#101014] px-4 py-4 shadow-lg">
                    <Restraint outcome={scenario.outcome} />
                </div>
            </div>
        );
    }

    // One frame per thing sent, stacked under one eyebrow: a run that replies
    // to the lead AND briefs the team shows both, each in its destination.
    return (
        <div className="mt-6">
            <OutcomeEyebrow sent />
            <div className="space-y-3">
                {artifacts.map((artifact, i) => {
                    const isEmail = isEmailShaped(artifact);
                    return (
                        <div
                            key={i}
                            className="overflow-hidden rounded-xl border border-[#26262c] shadow-lg"
                        >
                            {!isEmail && artifact.to && (
                                <DestinationBar icons={icons} artifact={artifact} />
                            )}
                            <div className="bg-[#0c0c0f] px-4 py-3.5">
                                <OutboundMessage
                                    icons={icons}
                                    artifact={artifact}
                                    hideDestination={!isEmail}
                                />
                            </div>
                        </div>
                    );
                })}
            </div>
        </div>
    );
}

/** Done, and nothing went out — on purpose. Restraint rendered as a result,
    not as an empty screen: an agent that declines to spam the team is doing
    the job, and the rehearsal should say so in as many words. */
function Restraint({ outcome }: { outcome?: string }) {
    return (
        <div>
            <p className="m-0 flex items-center gap-2.5 text-[13.5px] font-medium">
                <Check className="h-4 w-4 shrink-0 text-emerald-400" />
                Nothing to send
            </p>
            {/* The agent's closing words are usually markdown (a digest with
                headings, bold, lists) — raw ### and ** made the payoff read
                as broken. Full-width and flush left: the check is the title
                row's mark, not a gutter the whole digest indents under. */}
            <MarkdownRenderer
                content={outcome ?? 'It decided nothing needed to go out.'}
                className="mt-2 text-[12.5px] leading-relaxed text-foreground/55"
            />
        </div>
    );
}

export function LeadCard({
    scenario,
    icons,
    run,
    triggers,
    onTrigger,
    collapsed = false,
    editing = false,
    onToggleEdit,
    onPatch,
    runButton = true,
}: {
    scenario: Scenario;
    icons: VariantProps['icons'];
    run: ReplayState;
    triggers: TriggerFixture[];
    onTrigger: (slug: string) => void;
    collapsed?: boolean;
    editing?: boolean;
    onToggleEdit?: () => void;
    onPatch?: (patch: LeadPatch) => void;
    /** False = the host owns the run affordance (the Setup preview renders
        its own large button below the card). */
    runButton?: boolean;
}) {
    return (
        // No overflow clip: the node-type menu opens past the card's edge.
        <div className={cn('rounded-xl', CARD)}>
            <div
                className={cn(
                    'flex items-center gap-2.5 px-3 py-2',
                    !collapsed && 'border-b border-foreground/8'
                )}
            >
                <NodeTypeDropdown
                    triggers={triggers}
                    current={scenario.key.split(':')[0]}
                    onTrigger={onTrigger}
                    icons={icons}
                />
                {collapsed && (
                    <span className="min-w-0 flex-1 truncate text-[12.5px] text-foreground/50">
                        {scenario.lead.title} · {scenario.lead.meta}
                    </span>
                )}
                <span className="ml-auto flex items-center gap-1.5">
                    {onToggleEdit && !collapsed && (
                        <EditControls
                            editing={editing}
                            onToggleEdit={onToggleEdit}
                            disabled={run.phase === 'running'}
                        />
                    )}
                    {collapsed && runButton && <RunTest run={run} />}
                </span>
            </div>
            {!collapsed && (
                <div className="px-4 pb-3.5 pt-3.5">
                    <InboundMessage
                        scenario={scenario}
                        edit={editing && onPatch ? { onPatch } : undefined}
                    />
                    {runButton && (
                        <div className="mt-4 flex justify-end">
                            <RunTest run={run} />
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}

/* ------------------------------------------------------------ A. stacked */

export function VariantStack({
    run,
    scenario,
    icons,
    editing,
    onToggleEdit,
    onPatch,
    traceStyle,
    triggers,
    onTrigger,
}: VariantProps) {
    const done = run.phase === 'done';
    return (
        <div className="mx-auto w-full max-w-[560px]">
            <LeadCard
                scenario={scenario}
                icons={icons}
                run={run}
                triggers={triggers}
                onTrigger={onTrigger}
                collapsed={run.phase !== 'idle'}
                editing={editing}
                onToggleEdit={onToggleEdit}
                onPatch={onPatch}
            />

            {run.phase !== 'idle' && (
                <div className={cn('mt-3 overflow-hidden rounded-xl', CARD)}>
                    <div className="flex items-center justify-between gap-3 border-b border-foreground/8 px-4 py-2.5">
                        <span className="text-[11px] font-semibold uppercase tracking-[0.1em] text-foreground/30">
                            {done ? 'What it did' : 'What it’s doing'}
                        </span>
                        <StandIn />
                    </div>
                    <Trace rows={run.rows} icons={icons} styleVariant={traceStyle} running={run.phase === 'running'} className="py-1" />
                </div>
            )}

            {done && (
                <Outcome run={run} scenario={scenario} icons={icons} />
            )}
        </div>
    );
}

/* ------------------------------------------------------ B. conversation */

export function VariantConversation({
    run,
    scenario,
    icons,
    editing,
    onToggleEdit,
    onPatch,
    traceStyle,
    triggers,
    onTrigger,
}: VariantProps) {
    return (
        <div className="mx-auto w-full max-w-[560px]">
            <div className="flex gap-3">
                {/* Full column width, same as the trace and outcome below and
                    the header above: the 85% chat-bubble cap left the screen's
                    primary card ragged against every other right edge. */}
                <div
                    className={cn(
                        'w-full min-w-0 rounded-2xl rounded-tl-md px-4 py-3',
                        CARD
                    )}
                >
                    <div className="mb-2 flex items-center gap-1.5">
                        <NodeTypeDropdown
                            triggers={triggers}
                            current={scenario.key.split(':')[0]}
                            onTrigger={onTrigger}
                            icons={icons}
                        />
                        <span className="ml-auto">
                            <EditControls
                                editing={editing}
                                onToggleEdit={onToggleEdit}
                                disabled={run.phase === 'running'}
                            />
                        </span>
                    </div>
                    <InboundMessage
                        scenario={scenario}
                        edit={editing ? { onPatch } : undefined}
                    />
                    <div className="mt-3 flex justify-end">
                        <RunTest run={run} />
                    </div>
                </div>
            </div>

            {run.phase !== 'idle' && (
                <Trace rows={run.rows} icons={icons} dense styleVariant={traceStyle} running={run.phase === 'running'} className="my-3" />
            )}

            {run.phase === 'done' && (
                <Outcome run={run} scenario={scenario} icons={icons} />
            )}
        </div>
    );
}

/** The finished run, read-only: trigger identity + inbound card + trace +
    outcome, no controls. The public share page's whole body — it renders a
    SNAPSHOT, so `run` is always a completed state and nothing re-runs. */
export function RunReadout({
    run,
    scenario,
    icons,
}: Pick<VariantProps, 'run' | 'scenario' | 'icons'>) {
    const running = run.phase === 'running';
    return (
        <div className="mx-auto w-full max-w-[560px]">
            <div
                className={cn(
                    'w-full min-w-0 rounded-2xl rounded-tl-md px-4 py-3',
                    CARD
                )}
            >
                <div className="mb-2 flex items-center gap-1.5">
                    <span className="-ml-1 flex items-center gap-2.5 px-2 py-1.5">
                        <TriggerMark
                            provider={scenario.iconSlug ?? scenario.provider}
                            icons={icons}
                        />
                        <span className="text-[13.5px] font-medium">
                            {scenario.nodeName}
                        </span>
                    </span>
                </div>
                <InboundMessage scenario={scenario} />
            </div>
            {(run.rows.length > 0 || running) && (
                <Trace
                    rows={run.rows}
                    icons={icons}
                    dense
                    styleVariant="cards"
                    running={running}
                    className="my-3"
                />
            )}
            {run.phase === 'done' && (
                <Outcome run={run} scenario={scenario} icons={icons} />
            )}
        </div>
    );
}

/* ------------------------------------------------------------- C. stage */

export function VariantStage({
    run,
    scenario,
    icons,
    editing,
    onToggleEdit,
    onPatch,
    traceStyle,
    triggers,
    onTrigger,
}: VariantProps) {
    const done = run.phase === 'done';
    return (
        <div className="mx-auto grid w-full max-w-[1060px] gap-4 lg:grid-cols-[1fr_1.15fr_1fr] lg:items-start">
            <LeadCard
                scenario={scenario}
                icons={icons}
                run={run}
                triggers={triggers}
                onTrigger={onTrigger}
                editing={editing}
                onToggleEdit={onToggleEdit}
                onPatch={onPatch}
            />

            <div className={cn('overflow-hidden rounded-xl', CARD)}>
                <div className="flex items-center justify-between gap-3 border-b border-foreground/8 px-4 py-2.5">
                    <span className="inline-flex items-center gap-2">
                        <Glyph mark={icons.agent} className="h-3.5 w-3.5" />
                        <span className="text-[11px] font-semibold uppercase tracking-[0.1em] text-foreground/30">
                            {done ? 'What it did' : run.phase === 'idle' ? 'The agent' : 'Working'}
                        </span>
                    </span>
                    <StandIn />
                </div>
                {run.phase === 'idle' ? (
                    <p className="m-0 px-4 py-3 text-[12.5px] text-foreground/35">
                        Waiting for the run.
                    </p>
                ) : (
                    <Trace rows={run.rows} icons={icons} styleVariant={traceStyle} running={run.phase === 'running'} className="py-1" />
                )}
            </div>

            <div
                className={cn(
                    'overflow-hidden rounded-xl transition-opacity',
                    CARD,
                    !done && 'opacity-40'
                )}
            >
                <div className="flex items-center justify-between gap-2 border-b border-foreground/8 px-4 py-2.5">
                    <span className="inline-flex items-center gap-2">
                        <Glyph
                            mark={icons[scenario.artifacts?.[0]?.provider ?? 'agent']}
                            className="h-3.5 w-3.5"
                        />
                        <span className="text-[11px] font-semibold uppercase tracking-[0.1em] text-foreground/30">
                            Would go out
                        </span>
                    </span>
                    <span className="text-[11.5px] text-foreground/35">not sent</span>
                </div>
                <div className="px-4 py-3.5">
                    {run.artifacts?.length ? (
                        <div className="space-y-4">
                            {run.artifacts.map((a, i) => (
                                <OutboundMessage key={i} icons={icons} artifact={a} />
                            ))}
                        </div>
                    ) : done ? (
                        <Restraint outcome={scenario.outcome} />
                    ) : (
                        <p className="m-0 text-[12.5px] text-foreground/35">
                            {run.phase === 'running'
                                ? 'Nothing yet — it is still working.'
                                : 'Nothing yet.'}
                        </p>
                    )}
                </div>
            </div>
        </div>
    );
}

/* ---------------------------------------------------------- D. timeline */

export function VariantTimeline({ run, scenario, icons, traceStyle }: VariantProps) {
    const Row = ({
        at,
        live,
        children,
    }: {
        at: string;
        live?: boolean;
        children: React.ReactNode;
    }) => (
        <div className="relative flex gap-4 pb-5 last:pb-0">
            <span className="w-11 shrink-0 pt-0.5 text-right font-mono text-[11px] tabular-nums text-foreground/30">
                {at}
            </span>
            <span
                className={cn(
                    'relative mt-1.5 h-2 w-2 shrink-0 rounded-full',
                    live ? 'bg-foreground/40' : 'bg-emerald-400/80'
                )}
            />
            <div className="min-w-0 flex-1">{children}</div>
        </div>
    );

    return (
        <div className="mx-auto w-full max-w-[560px]">
            <div className="mb-4 flex items-center justify-between gap-3">
                <span className="text-[11px] font-semibold uppercase tracking-[0.1em] text-foreground/30">
                    Rehearsal record
                </span>
                <span className="flex items-center gap-3">
                    <StandIn />
                    <RunTest run={run} />
                </span>
            </div>
            <Row at="0.0s">
                <p className="m-0 flex items-center gap-2 text-[13px] text-foreground/85">
                    <TriggerMark provider={scenario.iconSlug ?? scenario.provider} icons={icons} className="h-3 w-3 shrink-0" />
                    {scenario.lead.title}
                    <span className="truncate font-mono text-[11px] text-foreground/40">
                        {scenario.lead.meta}
                    </span>
                </p>
            </Row>
            {run.phase === 'running' && run.rows.length === 0 && (
                <Row at="" live>
                    <p className="m-0 flex items-center gap-2 text-[13px] text-foreground/45">
                        <Loader2 className="h-3 w-3 animate-spin" /> Thinking
                    </p>
                </Row>
            )}
            {run.rows.map((r) =>
                r.kind === 'thought' ? (
                    <Row key={r.id} at={sec(r.at)}>
                        <p className="m-0 text-[12.5px] italic leading-relaxed text-foreground/45">
                            {r.text}
                        </p>
                    </Row>
                ) : (
                    <Row
                        key={r.id}
                        at={r.status === 'completed' && r.ms != null ? sec(r.ms) : sec(r.elapsed)}
                        live={r.status !== 'completed'}
                    >
                        <div className={cn('-mx-1 overflow-hidden rounded-lg')}>
                            <TraceRow row={r} icons={icons} dense styleVariant={traceStyle} />
                        </div>
                    </Row>
                )
            )}
            {run.phase === 'done' && (
                <Row at={sec(run.t)}>
                    {run.artifacts?.length ? (
                        <div className="space-y-3">
                            {run.artifacts.map((a, i) => (
                                <div key={i} className={cn('overflow-hidden rounded-xl', CARD)}>
                                    <div className="flex items-center justify-between border-b border-foreground/8 px-4 py-2">
                                        <span className="text-[11px] font-semibold uppercase tracking-[0.1em] text-foreground/30">
                                            Would have sent
                                        </span>
                                        <span className="text-[11.5px] text-foreground/35">
                                            not sent
                                        </span>
                                    </div>
                                    <div className="px-4 py-3">
                                        <OutboundMessage icons={icons} artifact={a} />
                                    </div>
                                </div>
                            ))}
                        </div>
                    ) : (
                        <Restraint outcome={scenario.outcome} />
                    )}
                </Row>
            )}
        </div>
    );
}
