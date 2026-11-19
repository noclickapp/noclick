// Adding a trigger, search first: "What should trigger Support?", where what you type suggests a schedule, apps'
// events (connected apps first) and the kinds whose words match; empty, example pills and every kind. Then the kind's
// own setup (a schedule in plain words, an app's event with its account connected in place and its filters, its inbox,
// a channel, a number, a webhook, a NoClick event), what it should do then, the trigger read back in the agent's own
// words, and Add. It replaces the Triggers tab's list while it's open.
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { toast } from 'sonner';
import { ArrowLeft, Check, ChevronRight, Phone, Plus, Search, X } from 'lucide-react';
import { Agent, Channel, Connection, Cron, Inbox, OnEvent, OnPlatformEvent, OnWebhook, PhoneNumber, Workspace, type JsonObject } from 'noclick';
import { HAIRLINE } from '@/ui/primitives';
import { BUTTON_GHOST, BUTTON_PRIMARY } from '@/ui/buttons';
import { useWork } from '../context';
import { cn } from '@/ui/utils';
import { errorText } from '@/screens/console/pages/resources/shared';
import { useWorkClient } from '../client';
import { useAgentFaces, useWorkV1 } from '../agents/reads';
import { MemberAvatar } from '@/screens/channels/avatars';
import { rereadAgent } from '../profile/reads';
import { rereadAccounts } from '../newAgent/catalog';
import { AppMark, useAppConnections, useEventApps, useIntegrationEvents } from '../newAgent/wakes';
import type { EventApp } from '../newAgent/infer';
import { describeEvent, KindIcon, type TriggerActions } from './data';
import { eventLabel, longWhen, PLATFORM_EVENTS, readSchedule, sentenceOf, type Names, type TriggerItem, type TriggerKind } from './model';
import { FIELD, INPUT, LABEL, NOTE, PILL, PILL_OFF, Pills, ScheduleField, ThenField, localZone } from './parts';
import { openTabForLater } from '@/lib/oauthPopup';

export type AddKind = 'cron' | 'event' | 'email' | 'channel' | 'call' | 'webhook' | 'platform';

/** How adding one starts: a kind, a schedule's words, an app's event (a stopped one's replacement). */
export interface AddSeed {
    kind?: AddKind;
    words?: string;
    integration?: string;
    /** An app event's connection, by name (its integration is read from it). */
    connection?: string;
    event?: string;
}

const KINDS: { kind: AddKind; title: string; line: string; words: string }[] = [
    { kind: 'cron', title: 'On a schedule', line: 'Every weekday at 9, every hour', words: 'schedule every daily weekly hourly hour minute morning evening night monday tuesday wednesday thursday friday weekday weekend time cron' },
    { kind: 'event', title: 'When something happens in an app', line: 'An issue opened, a payment, a new row', words: 'app event github stripe slack gmail sheet form issue payment' },
    { kind: 'email', title: 'When someone emails it', line: 'Its own address', words: 'email emails inbox mail address' },
    { kind: 'channel', title: 'In a channel', line: 'When it’s @mentioned, or every message', words: 'channel mention mentioned post message chat thread' },
    { kind: 'call', title: 'When someone calls', line: 'One of your numbers rings it', words: 'call calls phone number ring voice' },
    { kind: 'webhook', title: 'From your own code', line: 'Its own URL your code posts to', words: 'webhook url http post api code request curl' },
    { kind: 'platform', title: 'When something happens in NoClick', line: 'A run fails, an agent asks you', words: 'noclick fail failed fails run error agent asks deploy payment disconnected spend cap' },
];
const KIND_OF = Object.fromEntries(KINDS.map((k) => [k.kind, k])) as Record<AddKind, (typeof KINDS)[number]>;

const DEFAULT_MESSAGE: Record<AddKind, string> = {
    cron: 'Go through what’s new and do what’s needed',
    event: 'Look at it and do what’s needed',
    email: 'Answer it, or tell you if it needs you',
    channel: 'Answer in the thread',
    call: 'Take the call and write you what they needed',
    webhook: 'Read what came in and act on it',
    platform: 'Find out what happened and tell you',
};
/** Apps people reach for, after their own. */
const POPULAR = ['gmail', 'stripe', 'google-sheets', 'hubspot', 'shopify', 'typeform', 'notion', 'jira', 'github', 'slack'];

type Senders = 'anyone' | 'users' | 'owner';
const SENDERS: { id: Senders; label: string }[] = [
    { id: 'anyone', label: 'Anyone' },
    { id: 'users', label: 'People in the space' },
    { id: 'owner', label: 'Only you' },
];

interface Draft {
    kind?: AddKind;
    words: string;
    tz: string;
    integration?: string;
    event?: string;
    filters: Record<string, string>;
    senders: Senders;
    channelId?: string;
    mode?: 'mentions' | 'all';
    numberId?: string;
    hook: string;
    platform?: string;
    message: string;
}
const empty = (): Draft => ({ words: '', tz: localZone(), filters: {}, senders: 'anyone', hook: '', message: '' });

export function AddTrigger({ agent, name, phone, seed, actions, onCancel, onAdded }: { agent: Agent; name: string; phone: boolean; seed: AddSeed; actions: TriggerActions; onCancel: () => void; onAdded: (id: string) => void }) {
    const client = useWorkClient();
    const { openPage } = useWork();
    const connections = useAppConnections();
    const apps = useEventApps();
    const [draft, setDraft] = useState<Draft>(() => ({ ...empty(), kind: seed.kind, words: seed.words ?? '', integration: seed.integration, event: seed.event }));
    // A stopped one's replacement names its connection: its app is read from it.
    useEffect(() => {
        if (!seed.connection || draft.integration) return;
        const known = [...connections.values()].find((c) => c.name === seed.connection);
        if (known) setDraft((d) => ({ ...d, integration: known.integration }));
    }, [seed.connection, connections, draft.integration]);
    const set = (patch: Partial<Draft>) => setDraft((d) => ({ ...d, ...patch }));
    const pick = (patch: Partial<Draft>) => setDraft({ ...empty(), ...patch });
    const app = apps.data?.find((a) => a.integration === draft.integration);
    const events = useIntegrationEvents(draft.kind === 'event' ? draft.integration : undefined);
    const filters = Object.entries(((events.data?.find((e) => e.name === draft.event)?.filters ?? {}) as Record<string, string>)).map(([n, about]) => ({ name: n, about: about.replace(/^required\.?\s*/i, ''), required: /^required\.?/i.test(about) }));
    const connection = draft.integration ? connections.get(draft.integration) : undefined;
    const channels = useWorkV1(draft.kind === 'channel' ? 'work:channels:open' : null, (c) => Channel.list({ client: c, status: 'open' }));
    const numbers = useWorkV1(draft.kind === 'call' ? 'work:phone-numbers' : null, (c) => PhoneNumber.list({ client: c }));
    const [busy, setBusy] = useState(false);
    const scroller = useRef<HTMLDivElement>(null);
    // Braced: Chrome's scrollTo answers with a promise, which React would take for the cleanup and call.
    useEffect(() => {
        scroller.current?.scrollTo({ top: 0 });
    }, [draft.kind]);

    const ready = (() => {
        switch (draft.kind) {
            case 'cron':
                return !!readSchedule(draft.words);
            case 'event':
                return !!draft.event && !!connection?.connected && filters.every((f) => !f.required || draft.filters[f.name]?.trim());
            case 'channel':
                return !!draft.channelId;
            case 'call':
                return !!draft.numberId;
            case 'webhook':
                return !!draft.hook.trim();
            case 'platform':
                return !!draft.platform;
            case 'email':
                return true;
            default:
                return false;
        }
    })();
    const message = draft.message.trim() || (draft.kind ? DEFAULT_MESSAGE[draft.kind] : '');
    const channel = channels.data?.find((c) => c.id === draft.channelId);
    const number = numbers.data?.find((n) => n.id === draft.numberId);
    const names: Names = { appOf: () => app?.label ?? 'the app' };
    // The draft as a trigger, for its sentence.
    const preview: TriggerItem | null = draft.kind
        ? {
              id: 'draft',
              kind: draft.kind,
              spec: {
                  cron: readSchedule(draft.words)?.expr ?? '',
                  tz: draft.tz,
                  connection: connection?.name ?? '',
                  event: draft.event ?? '',
                  filters: Object.fromEntries(Object.entries(draft.filters).filter(([, v]) => v.trim())),
                  senders: draft.senders,
                  address: 'its inbox',
                  name: draft.kind === 'channel' ? (channel?.name ?? '') : draft.hook.trim(),
                  mode: draft.mode ?? channel?.mode ?? 'mentions',
                  number: number?.number ?? '',
                  type: draft.platform ?? '',
                  // Only what it's told: an inbox, a number and a channel take none.
                  message: draft.kind === 'email' || draft.kind === 'call' || draft.kind === 'channel' ? '' : message,
              },
              title: null,
              summary: null,
              state: 'live',
              pausedItself: false,
              reason: null,
              fix: null,
              nextAt: null,
              lastAt: null,
              setBy: 'person',
              readOnly: false,
              actions: [],
              url: null,
              running: false,
          }
        : null;
    // As its row will say it.
    const readBack = preview && sentenceOf(preview, names);

    const add = async () => {
        if (!ready || !draft.kind) return;
        setBusy(true);
        const me = Agent.fromId(agent.id, { client });
        const done = (id: string, undo?: () => Promise<unknown>) => {
            rereadAgent(agent.id);
            toast('Added', { description: readBack ?? undefined, ...(undo && { action: { label: 'Undo', onClick: () => void undo().then(() => rereadAgent(agent.id)) } }) });
            onAdded(id);
        };
        try {
            switch (draft.kind) {
                case 'cron': {
                    const id = await actions.add(new Cron(readSchedule(draft.words)!.expr, { tz: draft.tz, message }));
                    if (id) done(id, () => me.removeTrigger(id));
                    break;
                }
                case 'event': {
                    const id = await actions.add(new OnEvent(connection!.name, draft.event!, { filters: preview!.spec.filters as JsonObject, message }));
                    if (id) done(id, () => me.removeTrigger(id));
                    break;
                }
                case 'webhook': {
                    const id = await actions.add(new OnWebhook(draft.hook.trim().toLowerCase().replace(/[^a-z0-9-]+/g, '-'), { message }));
                    if (id) done(id, () => me.removeTrigger(id));
                    break;
                }
                case 'platform': {
                    const id = await actions.add(new OnPlatformEvent(draft.platform!, { message }));
                    if (id) done(id, () => me.removeTrigger(id));
                    break;
                }
                case 'email': {
                    const inbox = await Inbox.create({ client, agent: agent.id, senders: draft.senders });
                    done(inbox.id, () => inbox.delete());
                    break;
                }
                case 'call': {
                    await number!.answerWith(agent.id);
                    done(number!.id, () => number!.disconnect());
                    break;
                }
                case 'channel': {
                    // A space's channel takes its agents from the space: it joins the space first.
                    if (channel!.workspaceId) {
                        const space = await Workspace.get(channel!.workspaceId, { client, user: null });
                        if (!space.members.some((m) => m.agentId === agent.id)) await space.add(me);
                    }
                    await Channel.fromId(channel!.id, { client, user: null }).add({ agentId: agent.id });
                    if (draft.mode && draft.mode !== channel!.mode) await Channel.fromId(channel!.id, { client, user: null }).update({ mode: draft.mode });
                    done(channel!.id);
                    break;
                }
            }
        } catch (error) {
            toast('Couldn’t add it', { description: errorText(error) });
        } finally {
            setBusy(false);
        }
    };

    const back = draft.kind ? () => setDraft(empty()) : onCancel;
    return (
        <div className="flex min-h-full flex-col" data-testid="add-trigger">
            <div className="flex shrink-0 items-center gap-2 px-5 pb-1 pt-4">
                <button type="button" aria-label={draft.kind ? 'Back to every kind' : 'Back to its triggers'} onClick={back} className="-ml-1.5 grid h-8 w-8 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground">
                    <ArrowLeft className="h-4 w-4" strokeWidth={2} />
                </button>
                <p className="text-[15px] font-semibold">{draft.kind ? KIND_OF[draft.kind].title : 'Add a trigger'}</p>
            </div>
            <div ref={scroller} className="flex-1 px-5 pb-6 pt-3">
                {!draft.kind ? (
                    <SearchPicker name={name} apps={apps.data ?? []} connected={(i) => !!connections.get(i)?.connected} onPick={pick} />
                ) : (
                    <div className="flex flex-col gap-5">
                        {draft.kind === 'cron' && <ScheduleField words={draft.words} onWords={(words) => set({ words })} tz={draft.tz} onTz={(tz) => set({ tz })} focusFirst />}
                        {draft.kind === 'event' && (
                            <EventSetup
                                draft={draft}
                                set={set}
                                apps={apps.data ?? []}
                                appsReady={!!apps.data}
                                app={app}
                                events={(events.data ?? []).map((e) => ({ name: String(e.name), description: describeEvent(typeof e.description === 'string' ? e.description : '') }))}
                                filters={filters}
                                connected={(i) => !!connections.get(i)?.connected}
                                account={connection?.connected ? (connection.account ?? connection.name) : null}
                                onConnect={async () => {
                                    const tab = openTabForLater();
                                    try {
                                        const made = connection ?? (await Connection.create(draft.integration!, { client, integration: draft.integration, allowExisting: true }));
                                        tab.go(made.connectUrl ?? (await made.request()).url);
                                        rereadAccounts();
                                    } catch (error) {
                                        tab.close();
                                        toast(`Couldn’t connect ${app?.label ?? 'it'}`, { description: errorText(error) });
                                    }
                                }}
                            />
                        )}
                        {draft.kind === 'email' && (
                            <>
                                <div>
                                    <span className={LABEL}>Its address</span>
                                    <p className="text-[13.5px] leading-snug">Its own address is made as you add it, named after {name}.</p>
                                    <p className={NOTE}>Forward mail there, or give it out. Each email lands in its one session, shared by everyone talking to it.</p>
                                </div>
                                <div>
                                    <span className={LABEL}>Who can email it</span>
                                    <Pills value={draft.senders} options={SENDERS} onChange={(senders) => set({ senders })} />
                                </div>
                            </>
                        )}
                        {draft.kind === 'channel' && (
                            <>
                                <div>
                                    <span className={LABEL}>Which channel</span>
                                    {!channels.data ? (
                                        <p className="text-[13px] text-muted-foreground">Loading your channels…</p>
                                    ) : (
                                        <Choices
                                            value={draft.channelId}
                                            onChange={(channelId) => set({ channelId, mode: undefined })}
                                            options={channels.data
                                                .filter((c) => c.raw.kind !== 'dm' && !c.members.some((m) => m.agentId === agent.id))
                                                .map((c) => ({ id: c.id, title: `#${c.name}`, line: c.topic || (c.mode === 'all' ? 'Agents answer every message' : 'Agents answer @mentions') }))}
                                            empty={`${name} is in every channel you have already.`}
                                        />
                                    )}
                                </div>
                                {channel && (
                                    <div>
                                        <span className={LABEL}>In #{channel.name}, agents answer</span>
                                        <Pills
                                            value={draft.mode ?? (channel.mode === 'all' ? 'all' : 'mentions')}
                                            options={[
                                                { id: 'mentions', label: '@mentions only' },
                                                { id: 'all', label: 'Every message' },
                                            ]}
                                            onChange={(mode) => set({ mode })}
                                        />
                                        <p className={NOTE}>It’s #{channel.name}’s own setting, so it applies to every agent there. Changing it needs the right to manage the channel.</p>
                                    </div>
                                )}
                            </>
                        )}
                        {draft.kind === 'call' && (
                            <div>
                                <span className={LABEL}>Which number</span>
                                {!numbers.data ? (
                                    <p className="text-[13px] text-muted-foreground">Loading your numbers…</p>
                                ) : (
                                    <Choices
                                        value={draft.numberId}
                                        onChange={(numberId) => set({ numberId })}
                                        icon={<Phone className="h-4 w-4 text-foreground/75" strokeWidth={1.8} />}
                                        options={numbers.data.map((n) => ({
                                            id: n.id,
                                            title: n.number,
                                            line: [n.raw.locality, n.raw.country].filter((x) => typeof x === 'string' && x).join(', ') + (n.agentId ? (n.agentId === agent.id ? ' · rings it already' : ' · rings another agent') : ' · rings no one yet'),
                                        }))}
                                        empty="You don’t have a number yet."
                                    />
                                )}
                                {openPage && (
                                    <button type="button" onClick={() => openPage('resources', { kind: 'numbers', new: '1' })} className="mt-1 flex w-full items-center gap-3 rounded-[14px] px-2 py-2.5 text-left text-[14px] text-foreground/85 transition-colors hover:bg-foreground/[0.05]">
                                        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full border border-dashed border-foreground/40">
                                            <Plus className="h-4 w-4" strokeWidth={2} />
                                        </span>
                                        Buy a number
                                    </button>
                                )}
                                <p className={NOTE}>Each call lands in its one session, shared by everyone talking to it. What else it does on calls is set on the number.</p>
                            </div>
                        )}
                        {draft.kind === 'webhook' && (
                            <label className="block">
                                <span className={LABEL}>Name it</span>
                                <span className={FIELD}>
                                    {/* eslint-disable-next-line jsx-a11y/no-autofocus -- it opens to name it */}
                                    <input autoFocus value={draft.hook} onChange={(e) => set({ hook: e.target.value })} placeholder="orders" aria-label="Its name" className={INPUT} />
                                </span>
                                <p className={NOTE}>Its URL is made as you add it. The URL is the key: anything that posts to it triggers {name}, so share it like one.</p>
                            </label>
                        )}
                        {draft.kind === 'platform' && (
                            <div>
                                <span className={LABEL}>When</span>
                                <Choices value={draft.platform} onChange={(platform) => set({ platform })} options={PLATFORM_EVENTS.map((p) => ({ id: p.type, title: p.when.charAt(0).toUpperCase() + p.when.slice(1), line: p.detail }))} />
                            </div>
                        )}
                        {draft.kind !== 'email' && draft.kind !== 'call' && draft.kind !== 'channel' && (draft.kind !== 'event' || connection?.connected) && (
                            <ThenField value={draft.message} onChange={(m) => set({ message: m })} placeholder={DEFAULT_MESSAGE[draft.kind]} />
                        )}
                        {ready && readBack && <ReadBack agent={agent} name={name} sentence={readBack} />}
                    </div>
                )}
            </div>
            <div className={cn('sticky bottom-0 flex shrink-0 items-center gap-2 border-t bg-background px-5 py-3', HAIRLINE)}>
                <button type="button" onClick={onCancel} className={cn(BUTTON_GHOST, 'h-9 px-3.5')}>
                    Cancel
                </button>
                {draft.kind && (
                    <button type="button" disabled={!ready || busy} onClick={() => void add()} className={cn(BUTTON_PRIMARY, 'ml-auto h-9 px-4', phone && 'flex-1 justify-center')}>
                        <Check className="h-4 w-4" strokeWidth={2.25} />
                        {busy ? 'Adding…' : 'Add trigger'}
                    </button>
                )}
            </div>
        </div>
    );
}

/** One row per choice, the picked one ticked. */
function Choices({ value, onChange, options, icon, empty }: { value: string | undefined; onChange: (id: string) => void; options: { id: string; title: string; line: string }[]; icon?: ReactNode; empty?: string }) {
    if (!options.length && empty) return <p className="text-[13px] text-muted-foreground">{empty}</p>;
    return (
        <div className="-mx-2 flex flex-col gap-px">
            {options.map((o) => (
                <button key={o.id} type="button" aria-pressed={value === o.id} onClick={() => onChange(o.id)} className={cn('flex items-center gap-3 rounded-[14px] px-2 py-2 text-left transition-colors hover:bg-foreground/[0.05]', value === o.id && 'bg-foreground/[0.06]')}>
                    {icon && <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-foreground/[0.06]">{icon}</span>}
                    <span className="min-w-0 flex-1">
                        <span className="block text-[14px] font-medium tabular-nums">{o.title}</span>
                        {o.line && <span className="block truncate text-[12.5px] text-muted-foreground">{o.line}</span>}
                    </span>
                    <span className={cn('grid h-5 w-5 shrink-0 place-items-center rounded-full', value === o.id ? 'bg-foreground text-background' : 'ring-1 ring-inset ring-foreground/25')}>{value === o.id && <Check className="h-3 w-3" strokeWidth={3} />}</span>
                </button>
            ))}
        </div>
    );
}

/** The trigger said back as the agent's own sentence: what Add will make. */
function ReadBack({ agent, name, sentence }: { agent: Agent; name: string; sentence: string }) {
    const face = useAgentFaces().get(agent.id) ?? { id: agent.id, kind: 'agent' as const, name };
    return (
        <div className="flex gap-3 rounded-[22px] bg-foreground/[0.04] p-4 ring-1 ring-inset ring-border dark:ring-foreground/[0.08]" data-testid="read-back">
            <MemberAvatar member={face} size={28} />
            <div className="min-w-0">
                <p className="text-[12px] text-muted-foreground">{name} will read it as</p>
                <p className="mt-1 text-[15px] leading-snug">“{sentence}”</p>
                <p className="mt-1.5 text-[12px] text-muted-foreground">Each time lands in its one session, shared by everyone talking to it. You can pause or change it from its Triggers tab.</p>
            </div>
        </div>
    );
}

interface Hit {
    key: string;
    icon: ReactNode;
    title: ReactNode;
    line: string;
    patch: Partial<Draft>;
}

/** One box: what you type suggests a schedule, apps' events and kinds; empty, examples and every kind. */
function SearchPicker({ name, apps, connected, onPick }: { name: string; apps: EventApp[]; connected: (integration: string) => boolean; onPick: (p: Partial<Draft>) => void }) {
    const [q, setQ] = useState('');
    const hits = useMemo<Hit[]>(() => {
        const query = q.trim().toLowerCase();
        if (!query) return [];
        const words = query.split(/\s+/).filter((w) => !['a', 'an', 'the', 'when', 'on', 'in', 'is', 'new', 'someone', 'it', 'me', 'to', 'its'].includes(w));
        const out: Hit[] = [];
        const s = readSchedule(query);
        if (s) out.push({ key: 'cron', icon: <KindIcon kind="cron" />, title: s.words, line: `On a schedule · next ${longWhen(s.next(1)[0])}`, patch: { kind: 'cron', words: q.trim() } });
        if (words.length) {
            const scored = apps
                .flatMap((a) =>
                    a.events.map((e) => {
                        const hay = `${a.label} ${a.integration} ${e.label}`.toLowerCase();
                        const all = words.every((w) => hay.includes(w));
                        const appHit = words.some((w) => a.label.toLowerCase().startsWith(w) || a.integration.startsWith(w));
                        return { a, e, score: all ? (appHit ? 3 : 1) + (connected(a.integration) ? 1 : 0) + (words.some((w) => e.label.toLowerCase().includes(w)) ? 1 : 0) : 0 };
                    })
                )
                .filter((x) => x.score > 0)
                .sort((x, y) => y.score - x.score)
                .slice(0, 5);
            for (const { a, e } of scored)
                out.push({
                    key: `${a.integration}:${e.name}`,
                    icon: <AppMark nodeType={a.nodeType} className="h-4 w-4" />,
                    title: (
                        <>
                            {a.label} <span className="text-muted-foreground">›</span> {e.label}
                        </>
                    ),
                    line: connected(a.integration) ? 'Connected' : `Connect ${a.label} as you add it`,
                    patch: { kind: 'event', integration: a.integration, event: e.name },
                });
        }
        for (const k of KINDS) if (k.kind !== 'cron' && k.kind !== 'event' && words.some((w) => w.length > 2 && k.words.includes(w))) out.push({ key: k.kind, icon: <KindIcon kind={k.kind as TriggerKind} />, title: k.title, line: k.line, patch: { kind: k.kind } });
        return out.slice(0, 7);
    }, [q, apps, connected]);
    const examples = ['every weekday at 9', 'github issue', 'an email to its inbox', 'a run fails'];
    return (
        <>
            <label className="flex h-12 items-center gap-2.5 rounded-full bg-foreground/[0.05] px-4 ring-1 ring-inset ring-border dark:ring-foreground/[0.1]">
                <Search className="h-4 w-4 shrink-0 text-muted-foreground" strokeWidth={2} />
                <input
                    // eslint-disable-next-line jsx-a11y/no-autofocus -- it opens to say what triggers it
                    autoFocus
                    value={q}
                    onChange={(e) => setQ(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && hits[0] && onPick(hits[0].patch)}
                    placeholder={`What should trigger ${name}?`}
                    aria-label={`What should trigger ${name}?`}
                    className="min-w-0 flex-1 bg-transparent text-[15px] outline-none placeholder:text-muted-foreground max-sm:text-[16px]"
                />
                {q && (
                    <button type="button" aria-label="Clear" onClick={() => setQ('')} className="grid h-6 w-6 place-items-center rounded-full text-muted-foreground hover:bg-foreground/[0.08]">
                        <X className="h-3.5 w-3.5" strokeWidth={2} />
                    </button>
                )}
            </label>
            {!q ? (
                <>
                    <p className="mb-2 mt-4 text-[12.5px] text-muted-foreground">Say it the way you’d tell someone, like</p>
                    <div className="flex flex-wrap gap-1.5">
                        {examples.map((x) => (
                            <button key={x} type="button" onClick={() => setQ(x)} className={cn(PILL, PILL_OFF)}>
                                {x}
                            </button>
                        ))}
                    </div>
                    <p className="mb-1 mt-5 text-xs font-medium text-muted-foreground">Or pick a kind</p>
                    <div className="-mx-2 flex flex-col gap-px">
                        {KINDS.map((k) => (
                            <button key={k.kind} type="button" onClick={() => onPick({ kind: k.kind })} className="group flex w-full items-center gap-3 rounded-[14px] px-2 py-2.5 text-left transition-colors hover:bg-foreground/[0.05]">
                                <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-foreground/[0.06]">
                                    <KindIcon kind={k.kind as TriggerKind} className="h-4 w-4" />
                                </span>
                                <span className="min-w-0 flex-1">
                                    <span className="block truncate text-[14px] font-medium">{k.title}</span>
                                    <span className="block truncate text-[12.5px] text-muted-foreground">{k.line}</span>
                                </span>
                                <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground/60 transition-transform group-hover:translate-x-0.5" strokeWidth={1.8} />
                            </button>
                        ))}
                    </div>
                </>
            ) : hits.length ? (
                <div className="-mx-2 mt-3 flex flex-col gap-px" data-testid="trigger-hits">
                    {hits.map((h, i) => (
                        <button key={h.key} type="button" onClick={() => onPick(h.patch)} className={cn('flex w-full items-center gap-3 rounded-[14px] px-2 py-2.5 text-left transition-colors hover:bg-foreground/[0.05]', i === 0 && 'bg-foreground/[0.04]')}>
                            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-foreground/[0.06]">{h.icon}</span>
                            <span className="min-w-0 flex-1">
                                <span className="block truncate text-[14px] font-medium">{h.title}</span>
                                <span className="block truncate text-[12.5px] text-muted-foreground">{h.line}</span>
                            </span>
                        </button>
                    ))}
                </div>
            ) : (
                <div className="mt-4 rounded-[20px] bg-foreground/[0.03] p-4 text-[13px] leading-snug text-muted-foreground">
                    Nothing matches “{q}”. Try an app’s name (“stripe”), a time (“every monday at 8”), or pick a kind.
                    <button type="button" onClick={() => setQ('')} className="mt-2 block text-foreground underline-offset-2 hover:underline">
                        Show every kind
                    </button>
                </div>
            )}
        </>
    );
}

/** An app's event, a step at a time: the app, its event, your account (connected in place), then what to listen to. */
function EventSetup({
    draft,
    set,
    apps,
    appsReady,
    app,
    events,
    filters,
    connected,
    account,
    onConnect,
}: {
    draft: Draft;
    set: (p: Partial<Draft>) => void;
    apps: EventApp[];
    appsReady: boolean;
    app: EventApp | undefined;
    events: { name: string; description: string }[];
    filters: { name: string; about: string; required: boolean }[];
    connected: (integration: string) => boolean;
    account: string | null;
    onConnect: () => Promise<void>;
}) {
    const [q, setQ] = useState('');
    const [connecting, setConnecting] = useState(false);
    const list = useMemo(() => {
        const query = q.trim().toLowerCase();
        if (query) return apps.filter((a) => `${a.label} ${a.integration}`.toLowerCase().includes(query)).slice(0, 12);
        const rank = (a: EventApp) => (connected(a.integration) ? 0 : POPULAR.includes(a.integration) ? 1 + POPULAR.indexOf(a.integration) / 100 : 2);
        return [...apps].sort((x, y) => rank(x) - rank(y)).slice(0, 10);
    }, [q, apps, connected]);
    const step = (n: number, title: string, done: boolean, body: ReactNode, chosen?: ReactNode, onChange?: () => void) => (
        <section className="flex gap-3">
            <span className={cn('mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full text-[12px] font-medium', done ? 'bg-foreground text-background' : 'bg-foreground/[0.08] text-muted-foreground')}>{done ? <Check className="h-3.5 w-3.5" strokeWidth={3} /> : n}</span>
            <div className="min-w-0 flex-1">
                <div className="flex min-h-6 items-center gap-2">
                    <p className="flex-1 text-[13.5px] font-medium">{title}</p>
                    {chosen && onChange && (
                        <button type="button" onClick={onChange} className="rounded-full px-2 text-[12.5px] text-muted-foreground hover:bg-foreground/[0.06] hover:text-foreground">
                            Change
                        </button>
                    )}
                </div>
                <div className="mt-1.5">{chosen ?? body}</div>
            </div>
        </section>
    );
    if (!appsReady) return <p className="text-[13px] text-muted-foreground">Loading the apps…</p>;
    const eventName = draft.event ? eventLabel(draft.event) : '';
    return (
        <div className="flex flex-col gap-4">
            {step(
                1,
                'The app',
                !!app,
                <>
                    <label className={cn(FIELD, 'h-9')}>
                        <Search className="h-3.5 w-3.5 shrink-0 text-muted-foreground" strokeWidth={2} />
                        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={`Search ${apps.length} apps`} aria-label="Search apps" className={cn(INPUT, 'text-[13.5px]')} />
                    </label>
                    {!q && <p className="mb-1 mt-3 text-[12px] text-muted-foreground">Yours, then popular</p>}
                    <div className="-mx-2 mt-1 flex flex-col gap-px">
                        {list.map((a) => (
                            <button key={a.integration} type="button" onClick={() => set({ integration: a.integration, event: undefined, filters: {} })} className="flex items-center gap-3 rounded-[14px] px-2 py-2 text-left transition-colors hover:bg-foreground/[0.05]">
                                <AppMark nodeType={a.nodeType} className="h-5 w-5" />
                                <span className="min-w-0 flex-1 truncate text-[14px]">{a.label}</span>
                                <span className="shrink-0 text-[12px] text-muted-foreground">{connected(a.integration) ? 'Connected' : `${a.events.length} ${a.events.length === 1 ? 'event' : 'events'}`}</span>
                            </button>
                        ))}
                        {!list.length && <p className="px-2 py-2 text-[13px] text-muted-foreground">No app called “{q}”. A webhook can take anything that posts.</p>}
                    </div>
                </>,
                app && (
                    <span className="inline-flex items-center gap-2 text-[14px]">
                        <AppMark nodeType={app.nodeType} className="h-5 w-5" />
                        {app.label}
                    </span>
                ),
                () => set({ integration: undefined, event: undefined, filters: {} })
            )}
            {app &&
                step(
                    2,
                    'What happens there',
                    !!draft.event,
                    <div className="-mx-2 flex flex-col gap-px">
                        {(events.length ? events : app.events.map((e) => ({ name: e.name, description: '' }))).map((e) => (
                            <button key={e.name} type="button" onClick={() => set({ event: e.name, filters: {} })} className="flex items-start gap-3 rounded-[14px] px-2 py-2 text-left transition-colors hover:bg-foreground/[0.05]">
                                <span className="min-w-0 flex-1">
                                    <span className="block text-[14px]">{eventLabel(e.name)}</span>
                                    {e.description && <span className="block truncate text-[12.5px] text-muted-foreground">{e.description}</span>}
                                </span>
                            </button>
                        ))}
                    </div>,
                    draft.event && <span className="text-[14px]">{eventName}</span>,
                    () => set({ event: undefined, filters: {} })
                )}
            {app &&
                draft.event &&
                step(
                    3,
                    'Your account',
                    !!account,
                    <div className="rounded-[20px] bg-foreground/[0.03] p-3.5 ring-1 ring-inset ring-border dark:ring-foreground/[0.07]">
                        <p className="text-[13px] leading-snug text-muted-foreground">It listens through your {app.label} account. Connect it once and every agent of yours can use it.</p>
                        <button
                            type="button"
                            disabled={connecting}
                            onClick={() => {
                                setConnecting(true);
                                void onConnect().finally(() => setConnecting(false));
                            }}
                            className={cn(BUTTON_PRIMARY, 'mt-3 h-9 px-4')}
                        >
                            <AppMark nodeType={app.nodeType} className="h-4 w-4" />
                            {connecting ? 'Connecting…' : `Connect ${app.label}`}
                        </button>
                    </div>,
                    account && (
                        <span className="text-[14px]">
                            Connected <span className="text-muted-foreground">· {account}</span>
                        </span>
                    )
                )}
            {app &&
                draft.event &&
                account &&
                step(
                    4,
                    'What it listens to',
                    true,
                    filters.length ? (
                        <div className="flex flex-col gap-2">
                            {filters.map((f) => (
                                <label key={f.name} className="block">
                                    <span className="block pb-1 text-[12px] text-muted-foreground">
                                        {eventLabel(f.name)}
                                        {!f.required && ' · optional'}
                                    </span>
                                    <input
                                        value={draft.filters[f.name] ?? ''}
                                        onChange={(e) => set({ filters: { ...draft.filters, [f.name]: e.target.value } })}
                                        placeholder={f.required ? f.about.slice(0, 48) : `Any ${eventLabel(f.name).toLowerCase()}`}
                                        aria-label={eventLabel(f.name)}
                                        className="h-9 w-full rounded-full bg-foreground/[0.05] px-3.5 text-[13.5px] outline-none placeholder:text-[hsl(var(--placeholder))] focus:bg-foreground/[0.08] max-sm:text-[16px]"
                                    />
                                </label>
                            ))}
                        </div>
                    ) : (
                        <p className="text-[13px] text-muted-foreground">Everything from your {app.label} account.</p>
                    )
                )}
        </div>
    );
}
