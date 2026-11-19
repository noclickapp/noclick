// An agent's Activity tab: what will wake it next (its pending wake-ups) and every time it worked, newest first: what
// it did, when, in which conversation, how it ended and what it cost.
import type { JsonObject, Operation, Wakeup } from 'noclick';
import { agoText } from '../agents/states';
import { useTurns, useWakeups } from './reads';

const firstLine = (text: string) => text.split('\n').find((l) => l.trim())?.trim() ?? '';
const clip = (text: string, n = 90) => (text.length > n ? `${text.slice(0, n - 1).trimEnd()}…` : text);

/** What a turn did, in a line: its title, else the start of its reply. */
function didOf(op: Operation): string {
    const raw = op.raw as JsonObject;
    const title = typeof raw.title === 'string' ? raw.title : null;
    const reply = ((op.result ?? {}) as JsonObject).text;
    return title ?? (typeof reply === 'string' && reply.trim() ? clip(firstLine(reply)) : 'A turn');
}

/** How it ended. */
function endedOf(op: Operation): string {
    if (op.status === 'succeeded') return 'Answered';
    if (op.status === 'failed') return `Failed: ${op.error?.message ?? 'it didn’t finish'}`;
    if (op.status === 'canceled') return 'Stopped';
    if (op.status === 'expired') return 'Expired';
    return op.status === 'awaiting_human' ? 'Waiting on you' : 'Working';
}

/** What it cost, where the turn reports it. */
function costOf(op: Operation): string | null {
    const result = (op.result ?? {}) as JsonObject;
    const usd = typeof result.cost_usd === 'number' ? result.cost_usd : typeof (result.model_usage as JsonObject | undefined)?.usd === 'number' ? ((result.model_usage as JsonObject).usd as number) : null;
    return usd === null ? null : `$${usd.toFixed(2)}`;
}

const at = (d: Date | null, now: number) => (d ? (now - d.getTime() < 0 ? `in ${agoText(d.getTime() - now).replace(' ago', '')}` : agoText(now - d.getTime())) : '');

export function AgentActivity({ agentId, name }: { agentId: string; name: string }) {
    const turns = useTurns(agentId);
    const wakeups = useWakeups(agentId);
    const now = Date.now();
    const pending = (wakeups.data ?? []) as Wakeup[];
    if (turns.error !== undefined && !turns.data) return <p className="px-5 py-6 text-sm text-muted-foreground">Couldn’t load what {name} did.</p>;
    if (!turns.data) return <p className="px-5 py-6 text-sm text-muted-foreground">Loading…</p>;
    if (!turns.data.length && !pending.length)
        return <p className="px-5 py-6 text-sm text-muted-foreground">Nothing yet. Each time {name} wakes, it shows here: what woke it, what it did and what it cost.</p>;
    return (
        <div className="px-5 py-3" data-testid="agent-activity">
            {pending.length > 0 && (
                <section className="pb-2">
                    <h3 className="pt-2 text-xs font-medium text-muted-foreground">Next</h3>
                    <ul>
                        {pending.map((w) => (
                            <li key={w.id} className="py-2.5">
                                <p className="truncate text-sm text-foreground">{clip(firstLine(w.note) || 'A wake-up it set')}</p>
                                <p className="mt-0.5 text-xs text-muted-foreground">
                                    {w.every ? 'Every time its schedule comes round' : `Wakes ${at(w.at, now)}`} · {w.conversation}
                                </p>
                            </li>
                        ))}
                    </ul>
                </section>
            )}
            <ul>
                {turns.data.map((op) => {
                    const cost = costOf(op);
                    const conversation = (op.raw as JsonObject).conversation;
                    return (
                        <li key={op.id} className="py-3" data-operation={op.id}>
                            <div className="flex items-baseline gap-2">
                                <span className="min-w-0 flex-1 truncate text-sm text-foreground">{didOf(op)}</span>
                                {cost && <span className="shrink-0 text-xs tabular-nums text-muted-foreground">{cost}</span>}
                            </div>
                            <p className={op.status === 'failed' ? 'mt-0.5 text-xs text-red-600 dark:text-red-400' : 'mt-0.5 text-xs text-muted-foreground'}>
                                {[at(op.createdAt, now), typeof conversation === 'string' ? conversation : null, endedOf(op)].filter(Boolean).join(' · ')}
                            </p>
                        </li>
                    );
                })}
            </ul>
        </div>
    );
}
