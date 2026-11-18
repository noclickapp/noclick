// An operation's time as a segmented bar, built from its recorded status
// events (never guessed from updated_at): waiting, running, and held segments
// (hatched), with durations above, phases below, and an agent turn's tool
// calls as ticks on the running segment.
import { Check, CircleX } from 'lucide-react';
import { cn } from '@/ui/utils';
import { formatDuration } from '@/screens/console/lib/format';

export interface TimelineEvent {
    status: string;
    at: Date | string | null;
}

export type TimelinePhase = 'wait' | 'run' | 'held';

export interface TimelineSegment {
    status: string;
    phase: TimelinePhase;
    start: number;
    end: number;
}

export interface TimelineTick {
    id: string;
    name: string;
    at: Date | string;
    durationMs: number | null;
}

const TERMINAL = new Set(['succeeded', 'failed', 'canceled', 'expired']);

function phaseOf(status: string): TimelinePhase {
    if (status === 'queued') return 'wait';
    return status === 'awaiting_human' ? 'held' : 'run';
}

function ms(at: Date | string | null): number | null {
    if (at == null) return null;
    const t = at instanceof Date ? at.getTime() : Date.parse(at);
    return Number.isNaN(t) ? null : t;
}

/** Three or more events, or any held time: otherwise one line says it ("Waited 120ms · ran 2.72s"). */
export function shouldShowTimeline(events: readonly TimelineEvent[]): boolean {
    return events.length >= 3 || events.some((e) => e.status === 'awaiting_human');
}

/** Segments between consecutive events; a non-terminal last event runs to `now`. */
export function timelineSegments(events: readonly TimelineEvent[], now: number): { segments: TimelineSegment[]; end: string | null } {
    const timed = events.map((e) => ({ status: e.status, at: ms(e.at) })).filter((e): e is { status: string; at: number } => e.at !== null);
    const segments: TimelineSegment[] = [];
    for (let i = 0; i < timed.length; i++) {
        const e = timed[i];
        if (TERMINAL.has(e.status)) break;
        const end = i + 1 < timed.length ? timed[i + 1].at : now;
        segments.push({ status: e.status, phase: phaseOf(e.status), start: e.at, end: Math.max(e.at, end) });
    }
    const last = timed[timed.length - 1];
    return { segments, end: last && TERMINAL.has(last.status) ? last.status : null };
}

/** The segment a tick belongs to, and where in it (0–100%): a tick lives inside its segment's box. */
export function placeTick(segments: readonly TimelineSegment[], at: number, durationMs: number | null): { index: number; left: number; width: number } | null {
    const last = segments.length - 1;
    const index = segments.findIndex((s, i) => at >= s.start && (at < s.end || (i === last && at === s.end)));
    if (index < 0) return null;
    const seg = segments[index];
    const span = Math.max(1, seg.end - seg.start);
    const width = durationMs ? (Math.min(durationMs, seg.end - at) / span) * 100 : 0;
    return { index, left: ((at - seg.start) / span) * 100, width };
}

const PHASE_LABEL: Record<TimelinePhase, string> = { wait: 'Queued', run: 'Running', held: 'Waiting' };
const HATCH = 'repeating-linear-gradient(135deg, hsl(var(--foreground) / var(--hatch)) 0 3px, transparent 3px 7px)';

export function ExecutionTimeline({
    events,
    now,
    ticks = [],
    onTick,
    className,
}: {
    events: readonly TimelineEvent[];
    now: number;
    ticks?: readonly TimelineTick[];
    onTick?: (id: string) => void;
    className?: string;
}) {
    const { segments, end } = timelineSegments(events, now);
    if (!segments.length) return null;
    // Segments keep a minimum width for their labels, so ticks are placed within their own segment, never on a global scale.
    const placed = ticks.flatMap((tick) => {
        const at = ms(tick.at);
        const place = at === null ? null : placeTick(segments, at, tick.durationMs);
        return place ? [{ tick, ...place }] : [];
    });
    return (
        <figure className={cn('m-0 flex items-center gap-2', className)} aria-label="Execution timeline">
            <div className="min-w-0 flex-1">
                <div className="flex gap-0.5 text-[12px] tabular-nums text-muted-foreground">
                    {segments.map((s, i) => (
                        <span key={i} className="min-w-[2.5rem] truncate" style={{ flexGrow: s.end - s.start || 1, flexBasis: 0 }}>
                            {formatDuration(s.end - s.start)}
                        </span>
                    ))}
                </div>
                <div className="my-1 flex h-2.5 gap-0.5 [--hatch:0.12] dark:[--hatch:0.08]">
                    {segments.map((s, i) => (
                        <span
                            key={i}
                            data-phase={s.phase}
                            className={cn(
                                'relative min-w-[2.5rem] rounded-sm',
                                s.phase === 'wait' && 'bg-foreground/20',
                                s.phase === 'run' && 'bg-foreground/60',
                                s.phase === 'held' && 'ring-1 ring-inset ring-foreground/25'
                            )}
                            style={{ flexGrow: s.end - s.start || 1, flexBasis: 0, backgroundImage: s.phase === 'held' ? HATCH : undefined }}
                        >
                            {placed
                                .filter((p) => p.index === i)
                                .map(({ tick, left, width }) => (
                                    <button
                                        key={tick.id}
                                        type="button"
                                        title={`${tick.name} · ${formatDuration(tick.durationMs)}`}
                                        aria-label={`${tick.name}, ${formatDuration(tick.durationMs)}`}
                                        onClick={() => onTick?.(tick.id)}
                                        className="absolute -top-0.5 h-3.5 min-w-[2px] rounded-[1px] bg-foreground hover:bg-foreground/70"
                                        style={{ left: `${left}%`, width: `${width}%` }}
                                    />
                                ))}
                        </span>
                    ))}
                </div>
                <div className="flex gap-0.5 text-[12px] text-muted-foreground">
                    {segments.map((s, i) => (
                        <span key={i} className="min-w-[2.5rem] truncate" style={{ flexGrow: s.end - s.start || 1, flexBasis: 0 }}>
                            {PHASE_LABEL[s.phase]}
                        </span>
                    ))}
                </div>
            </div>
            {end === 'succeeded' && <Check aria-label="Succeeded" className="h-4 w-4 shrink-0 text-foreground/70" strokeWidth={2.25} />}
            {end === 'failed' && <CircleX aria-label="Failed" className="h-4 w-4 shrink-0 text-red-600 dark:text-red-400" />}
        </figure>
    );
}
