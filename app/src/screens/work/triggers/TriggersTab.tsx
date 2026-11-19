// An agent's profile's Triggers tab, "Needs you first": what triggers it besides messages and @mentions, one compact
// line each, grouped Needs you (stopped), Live (the next run as an Up next pill) and Paused; the whole agent paused says
// so with Resume. A row opens in place to change, try, pause or remove it; + Add opens adding one in the list's place.
// An agent with none says it only answers when messaged, with ways to start.
import { useEffect, useState, type ReactNode } from 'react';
import { BellOff, Clock, Pause, Plus } from 'lucide-react';
import type { Agent } from 'noclick';
import { BUTTON_SECONDARY } from '@/ui/buttons';
import { cn } from '@/ui/utils';
import { AddTrigger, type AddSeed } from './AddTrigger';
import { useTriggerActions, useTriggerFrames, useTriggerItems, useTriggerNames } from './data';
import { nextRun, sentenceOf, shortWhen, type TriggerItem } from './model';
import { PILL, PILL_OFF } from './parts';
import { TriggerDetails } from './TriggerDetails';
import { TriggerRow } from './TriggerRow';

export interface TriggersTabProps {
    agent: Agent;
    name: string;
    phone: boolean;
    /** The trigger open in its row (from the URL), or null. */
    openId: string | null;
    onOpen: (id: string | null) => void;
    /** Adding one: null, or how it starts (a kind, an app's event). */
    adding: AddSeed | null;
    onAdding: (seed: AddSeed | null) => void;
}

const lowerFirst = (s: string) => s.charAt(0).toLowerCase() + s.slice(1).replace(/[.!]+$/, '');

export function TriggersTab({ agent, name, phone, openId, onOpen, adding, onAdding }: TriggersTabProps) {
    const { items, loading, error } = useTriggerItems(agent.id, agent.paused);
    const names = useTriggerNames();
    const actions = useTriggerActions(agent, names, (item) => onAdding({ kind: 'event', connection: String(item.spec.connection ?? ''), event: String(item.spec.event ?? '') }));
    useTriggerFrames(agent.id);
    const [fresh, setFresh] = useState<string | null>(null);
    // The one just added is marked until something else is opened.
    useEffect(() => {
        if (openId) setFresh(null);
    }, [openId]);

    if (adding)
        return (
            <AddTrigger
                agent={agent}
                name={name}
                phone={phone}
                seed={adding}
                actions={actions}
                onCancel={() => onAdding(null)}
                onAdded={(id) => {
                    onAdding(null);
                    setFresh(id);
                }}
            />
        );

    const row = (item: TriggerItem) => (
        <TriggerRow key={item.id} item={item} names={names} actions={actions} phone={phone} open={openId === item.id} onOpen={() => onOpen(openId === item.id ? null : item.id)} running={item.running} fresh={fresh === item.id}>
            <TriggerDetails item={item} names={names} actions={actions} agentName={name} />
        </TriggerRow>
    );
    const needs = items.filter((i) => i.state === 'stopped');
    // Paused with the agent, they're its: the line above says so, and each stays where it is.
    // The one just added on top.
    const live = items.filter((i) => i.state === 'live' || (agent.paused && i.state === 'paused' && !i.pausedItself)).sort((a, b) => Number(b.id === fresh) - Number(a.id === fresh));
    const paused = items.filter((i) => i.state === 'paused' && (!agent.paused || i.pausedItself));
    const next = nextRun(items);
    const head = (label: string, count: number, mark: ReactNode) => (
        <h3 className="mb-1 flex items-center gap-2 text-xs font-medium text-muted-foreground">
            {mark}
            {label}
            <span className="tabular-nums">{count}</span>
        </h3>
    );
    return (
        <div className="px-5 pb-10 pt-5" data-testid="agent-triggers">
            <div className="flex items-start gap-3">
                <div className="min-w-0 flex-1">
                    <p className="text-[15px] font-semibold">What triggers {name}</p>
                    <p className="mt-0.5 text-[12.5px] leading-snug text-muted-foreground">{items.length ? 'Besides messages to it and @mentions. Each lands in its one session, shared by everyone talking to it.' : 'Only messages and @mentions, for now.'}</p>
                </div>
                {items.length > 0 && (
                    <button
                        type="button"
                        aria-label="Add a trigger"
                        onClick={() => onAdding({})}
                        className="inline-flex h-7 shrink-0 items-center gap-1 rounded-full bg-foreground/[0.06] pl-2 pr-2.5 text-[12.5px] text-foreground/85 transition-colors hover:bg-foreground/[0.1] hover:text-foreground"
                    >
                        <Plus className="h-3.5 w-3.5" strokeWidth={2} />
                        Add
                    </button>
                )}
            </div>
            {agent.paused && (
                <div className="mt-4 flex items-center gap-2 rounded-xl bg-foreground/[0.05] py-1.5 pl-3 pr-1.5 text-[12.5px] text-foreground/80" data-testid="triggers-paused">
                    <BellOff className="h-3.5 w-3.5 shrink-0" strokeWidth={2} />
                    <span className="min-w-0 flex-1">Its triggers are paused: only messages and @mentions reach it.</span>
                    <button type="button" onClick={() => actions.setAgentPaused(false)} className={cn(BUTTON_SECONDARY, 'h-7 px-3 text-[12px]')}>
                        Resume
                    </button>
                </div>
            )}
            {loading ? (
                <div className="mt-4 flex flex-col gap-2" aria-label="Loading its triggers">
                    {[0, 1, 2].map((i) => (
                        <span key={i} className="h-10 animate-pulse rounded-[14px] bg-foreground/[0.04]" />
                    ))}
                </div>
            ) : error ? (
                <p className="mt-4 text-[13px] text-muted-foreground">Couldn’t load its triggers.</p>
            ) : !items.length ? (
                <NoTriggers name={name} onAdd={onAdding} />
            ) : (
                <div className={cn('mt-4 flex flex-col gap-4', agent.paused && 'opacity-60')}>
                    {needs.length > 0 && (
                        <section data-group="needs">
                            {head('Needs you', needs.length, <span className="h-2 w-2 rounded-full bg-red-500" />)}
                            <div className="-mx-2 flex flex-col gap-px">{needs.map(row)}</div>
                        </section>
                    )}
                    {live.length > 0 && (
                        <section data-group="live">
                            {head('Live', live.length, <span className="h-2 w-2 rounded-full bg-emerald-500" />)}
                            {next && !agent.paused && (
                                <button
                                    type="button"
                                    onClick={() => onOpen(next.item.id)}
                                    data-testid="up-next"
                                    className="mb-1 mt-1 flex h-9 w-full items-center gap-2 rounded-full bg-emerald-500/5 px-3 text-left ring-1 ring-inset ring-emerald-500/25 transition-colors hover:bg-emerald-500/15"
                                >
                                    <Clock className="h-3.5 w-3.5 shrink-0 text-emerald-600 dark:text-emerald-400" strokeWidth={2} />
                                    <span className="shrink-0 text-[12.5px] font-medium text-emerald-700 dark:text-emerald-300">Up next · {shortWhen(next.at)}</span>
                                    <span className="min-w-0 truncate text-[12.5px] text-foreground/80">I’ll {lowerFirst(sentenceOf(next.item, names).split(', I’ll ')[1] ?? '')}</span>
                                </button>
                            )}
                            <div className="-mx-2 flex flex-col gap-px">{live.map(row)}</div>
                        </section>
                    )}
                    {paused.length > 0 && (
                        <section data-group="paused">
                            {head('Paused', paused.length, <Pause className="h-3 w-3" strokeWidth={2.5} />)}
                            <div className="-mx-2 flex flex-col gap-px">{paused.map(row)}</div>
                        </section>
                    )}
                </div>
            )}
        </div>
    );
}

const SEEDS: { label: string; seed: AddSeed }[] = [
    { label: 'Every weekday at 9', seed: { kind: 'cron', words: 'every weekday at 9' } },
    { label: 'When an email reaches it', seed: { kind: 'email' } },
    { label: 'When it’s @mentioned in a channel', seed: { kind: 'channel' } },
];

/** An agent that only answers when messaged, and ways to start. */
function NoTriggers({ name, onAdd }: { name: string; onAdd: (seed: AddSeed) => void }) {
    return (
        <div className="mt-4 rounded-[22px] bg-foreground/[0.03] p-4 ring-1 ring-inset ring-border dark:ring-foreground/[0.07]" data-testid="no-triggers">
            <span className="grid h-10 w-10 place-items-center rounded-full bg-foreground/[0.06]">
                <span aria-hidden className="h-4 w-4 rounded-full border-[1.5px] border-dashed border-foreground/40" />
            </span>
            <p className="mt-3 text-[14px] leading-snug">{name} only answers when messaged.</p>
            <p className="mt-1 text-[12.5px] leading-snug text-muted-foreground">Give it a schedule, an app’s event, its own inbox or a webhook, and it’ll wake up for those too.</p>
            <div className="mt-3 flex flex-wrap gap-1.5">
                {SEEDS.map((s) => (
                    <button key={s.label} type="button" onClick={() => onAdd(s.seed)} className={cn(PILL, PILL_OFF)}>
                        <Plus className="h-3.5 w-3.5" strokeWidth={2} />
                        {s.label}
                    </button>
                ))}
                <button type="button" onClick={() => onAdd({})} className={cn(PILL, PILL_OFF)}>
                    Something else
                </button>
            </div>
        </div>
    );
}
