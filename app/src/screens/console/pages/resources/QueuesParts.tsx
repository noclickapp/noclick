// Pieces of the Queues panel that other pages use too: a message's status, the consumers line, the depth-over-time chart, and
// how an agent's queue trigger names its queue (linked to it when it resolves).
import { useState, type KeyboardEvent, type PointerEvent } from 'react';
import { Link } from 'react-router';
import { cn } from '@/ui/utils';
import { Queue, type QueueDepth, type QueueMessageStatus, type UsedBy } from 'noclick';
import type { StatusLook } from '@/screens/console/lib/status';
import { useConsole, useConsoleHref } from '@/screens/console/hooks/useConsole';
import { useV1 } from '@/sdk/useV1';

export function queuesMessageLook(status: QueueMessageStatus | string): StatusLook {
    switch (status) {
        case 'in_flight':
            return { label: 'In flight', glyph: 'filled', tone: 'ink' };
        case 'waiting':
            return { label: 'Waiting', glyph: 'hollow', tone: 'muted' };
        case 'delayed':
            return { label: 'Delayed', glyph: 'waiting', tone: 'muted' };
        case 'dead':
            return { label: 'Dead letter', glyph: 'cross', tone: 'failure' };
        default:
            return { label: status, glyph: 'muted', tone: 'muted' };
    }
}

/** Who takes a queue's messages: agents (by name, linked when `links`) and apps with their binding. */
export function QueuesConsumers({ users, links = false }: { users: readonly UsedBy[]; links?: boolean }) {
    const href = useConsoleHref();
    if (!users.length) return <span className="text-muted-foreground">Nothing yet</span>;
    // Read the way the other kinds say it: `support-bot (agent), booking as JOBS`.
    return (
        <span className="min-w-0 truncate">
            {users.map((u, i) => (
                <span key={`${u.kind}:${u.id}`}>
                    {i > 0 && ', '}
                    {u.kind === 'agent' && links ? (
                        <Link to={href(`agents/${u.id}`)} className="text-foreground underline-offset-2 hover:underline">
                            {u.name}
                        </Link>
                    ) : (
                        u.name
                    )}
                    {u.binding ? (
                        <span className="text-muted-foreground">
                            {' '}
                            as <span className="font-mono text-[12px]">{u.binding}</span>
                        </span>
                    ) : (
                        <span className="text-muted-foreground">{u.kind === 'agent' ? ' (agent)' : ' (app)'}</span>
                    )}
                </span>
            ))}
        </span>
    );
}

const CHART_H = 72;

const clock = (d: Date | null) => (d ? d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }) : '');

/**
 * How many messages waited over time: one ink line with a light wash, the latest point
 * marked, and a crosshair that reads out the nearest point on hover or with the arrow keys.
 */
export function QueuesDepthChart({ points, hours }: { points: readonly QueueDepth[]; hours: number }) {
    const [hover, setHover] = useState<number | null>(null);
    if (!points.length) return <p className="m-0 text-[13px] text-muted-foreground">No depth recorded yet.</p>;
    const max = Math.max(1, ...points.map((p) => p.depth));
    const peak = points.reduce((best, p) => (p.depth > best.depth ? p : best), points[0]);
    const last = points.length - 1;
    const x = (i: number) => (last ? (i / last) * 100 : 50);
    const y = (v: number) => CHART_H - 2 - (v / max) * (CHART_H - 10);
    const line = points.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(2)} ${y(p.depth).toFixed(2)}`).join(' ');
    const shown = hover ?? last;
    const point = points[shown];
    const pick = (e: PointerEvent<HTMLDivElement>) => {
        const box = e.currentTarget.getBoundingClientRect();
        setHover(Math.round(Math.min(1, Math.max(0, (e.clientX - box.left) / box.width)) * last));
    };
    const step = (e: KeyboardEvent<HTMLDivElement>) => {
        if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
        e.preventDefault();
        setHover(Math.min(last, Math.max(0, (hover ?? last) + (e.key === 'ArrowLeft' ? -1 : 1))));
    };
    const summary = `Waiting messages over the last ${hours} hours: peak ${peak.depth} at ${clock(peak.at)}, now ${points[last].depth}.`;
    return (
        <figure className="m-0 flex flex-col gap-1.5">
            <figcaption className="flex min-w-0 flex-wrap items-baseline justify-between gap-x-3 text-[12px] text-muted-foreground">
                <span>
                    <span className="text-[13px] font-medium tabular-nums text-foreground">{point.depth}</span> waiting · {point.inFlight} in flight
                    <span> · {hover === null ? 'now' : clock(point.at)}</span>
                </span>
                <span className="tabular-nums">
                    Peak {peak.depth} at {clock(peak.at)}
                </span>
            </figcaption>
            <div
                role="slider"
                aria-label={summary}
                aria-valuemin={0}
                aria-valuemax={last}
                aria-valuenow={shown}
                aria-valuetext={`${point.depth} waiting at ${clock(point.at)}`}
                tabIndex={0}
                onPointerMove={pick}
                onPointerLeave={() => setHover(null)}
                onKeyDown={step}
                onBlur={() => setHover(null)}
                className="relative w-full touch-pan-y rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
                style={{ height: CHART_H }}
            >
                <svg viewBox={`0 0 100 ${CHART_H}`} preserveAspectRatio="none" className="absolute inset-0 h-full w-full overflow-visible" aria-hidden>
                    <line x1={0} x2={100} y1={CHART_H - 2} y2={CHART_H - 2} stroke="hsl(var(--foreground) / 0.12)" strokeWidth={1} vectorEffect="non-scaling-stroke" />
                    <path d={`${line} L100 ${CHART_H - 2} L0 ${CHART_H - 2} Z`} fill="hsl(var(--foreground) / 0.05)" />
                    <path d={line} fill="none" stroke="hsl(var(--foreground) / 0.55)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
                </svg>
                {hover !== null && <span aria-hidden className="absolute inset-y-0 w-px bg-foreground/25" style={{ left: `${x(shown)}%` }} />}
                <span
                    aria-hidden
                    className={cn('absolute h-2 w-2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-foreground ring-2 ring-popover')}
                    style={{ left: `${x(shown)}%`, top: y(point.depth) }}
                />
            </div>
            <div aria-hidden className="flex justify-between text-[12px] tabular-nums text-muted-foreground">
                <span>{hours}h ago</span>
                <span>now</span>
            </div>
        </figure>
    );
}

/** An agent trigger's queue by name, linked to its drawer once it's found among the agent's user's queues. */
export function QueuesTriggerTitle({ name, batchSize, userId }: { name: string; batchSize: number; userId: string | null }) {
    const { client } = useConsole();
    const href = useConsoleHref();
    const found = useV1(name ? `queues?name=${name}&user=${userId ?? 'none'}` : null, () => Queue.fromName(name, { client, user: userId }).hydrate());
    return (
        <>
            Messages on{' '}
            {found.data ? (
                <Link to={href('resources/queues', { queue: found.data.id })} className="font-mono text-[13px] underline-offset-2 hover:underline">
                    {name}
                </Link>
            ) : (
                <span className="font-mono text-[13px]">{name}</span>
            )}
            <span className="font-normal text-muted-foreground"> · {batchSize > 1 ? `up to ${batchSize} a turn` : 'one a turn'}</span>
        </>
    );
}
