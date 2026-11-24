// What wakes a new agent, over the platform's real catalog (GET /v1/integrations: every app with events an agent's
// OnEvent trigger takes, and each event's filters), plus the built-ins: a schedule, its inbox, a webhook, a NoClick
// event. Messages and @-mentions always wake it. Picked from its job first, with a search behind "Add another"; an app
// not connected yet connects in place.
import { useEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';
import { ArrowLeft, AtSign, Bell, Check, ChevronRight, Clock, Mail, Plus, Search, Webhook, X } from 'lucide-react';
import { Connection, type JsonObject } from 'noclick';
import { NodeMark } from '@/ui/primitives';
import { getNodeIconMeta } from '@/lib/nodeIconRegistry';
import { fixWordCasing } from '@/lib/credentialLabels';
import { standing } from '@/slots';
import { APPS } from '../slots';
import { ShortcutTooltip } from '@/ui/ShortcutTooltip';
import { cn } from '@/ui/utils';
import { useWorkClient } from '../client';
import { useWorkV1 } from '../agents/reads';
import { rereadAccounts, useConnections } from './catalog';
import { BUILT_INS, eventWords, fromBuiltIn, fromEvent, wakeTitle, type EventApp, type Wake } from './infer';
import { openTabForLater } from '@/lib/oauthPopup';

const ROW = 'flex w-full items-start gap-2.5 rounded-xl px-2.5 py-2 text-left text-[13.5px] leading-5 transition-colors hover:bg-foreground/[0.05] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring';
/** A row's first line, 20px tall: what sits beside its text (a mark, a tick, a word) centres on it, and adds nothing
 *  under it, with a second line or without. */
const LINE = 'flex h-5 shrink-0 items-center';
const NOTE = 'block text-[12px] leading-snug text-muted-foreground';
const LABEL = 'px-2.5 pb-1 pt-2 text-[12px] text-muted-foreground';
const CHIP = 'inline-flex h-7 items-center gap-1.5 rounded-full px-2.5 text-[12.5px] transition-colors';
const CHIP_OFF = 'bg-foreground/[0.05] text-foreground/80 hover:bg-foreground/[0.09] hover:text-foreground';
const CHIP_ON = 'bg-foreground text-background';

const BUILT_IN_ICON = { schedule: Clock, inbox: Mail, webhook: Webhook, noclick: Bell } as const;

/** An app as the rest of NoClick names and draws it, from the node catalog the dashboard serves: the node named for
 *  its integration, else the Connections catalog's service for its own credential (GitHub acts through
 *  `automation-github-rest`). The API's own label is its id title-cased ("Github"), so it's never used. */
export function catalogApp(integration: string, credentialTypes: readonly string[] = []): { label: string; nodeType: string } {
    const named = `automation-${integration}`;
    const service = getNodeIconMeta(named) ? null : credentialTypes.length ? standing(APPS).serviceOf(credentialTypes[0]) : undefined;
    const nodeType = service?.value ?? named;
    return { label: getNodeIconMeta(nodeType)?.label ?? fixWordCasing(integration.replace(/[_-]+/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())), nodeType };
}

/** Every app whose events can wake an agent. */
export function useEventApps() {
    return useWorkV1('work:integrations:events', async (client) =>
        (await Connection.integrations(undefined, { client, kind: 'app' }))
            .filter((i) => i.events.length > 0)
            .map((i): EventApp => ({ integration: i.name, ...catalogApp(i.name, i.credentialTypes), events: i.events.map((name) => ({ name, label: eventWords(name) })) }))
    );
}

/** The account's connections, by integration: the connected one first. */
export function useAppConnections() {
    const connections = useConnections();
    return useMemo(() => {
        const by = new Map<string, Connection>();
        for (const c of connections.data ?? []) if (c.integration && (!by.has(c.integration) || (c.connected && !by.get(c.integration)!.connected))) by.set(c.integration, c);
        return by;
    }, [connections.data]);
}

export function AppMark({ nodeType, className }: { nodeType: string; className?: string }) {
    return <NodeMark type={nodeType} size="sm" className={className} />;
}

export function WakeMark({ wake, className = 'h-4 w-4' }: { wake?: Wake; className?: string }) {
    if (!wake) return <AtSign className={cn('shrink-0 text-foreground/70', className)} strokeWidth={1.75} />;
    if (wake.integration) return <AppMark nodeType={wake.nodeType ?? catalogApp(wake.integration).nodeType} className={className} />;
    const Icon = BUILT_IN_ICON[wake.builtin ?? 'webhook'];
    return <Icon className={cn('shrink-0 text-foreground/70', className)} strokeWidth={1.75} />;
}

function AlwaysRow() {
    return (
        <div className="flex items-start gap-2.5 px-2.5 py-2 text-[13.5px] leading-5">
            <span className={LINE}>
                <AtSign className="h-4 w-4 text-foreground/70" strokeWidth={1.75} />
            </span>
            <span className="min-w-0 flex-1">
                Messages and @-mentions
                <span className={NOTE}>Always: here and in channels it joins</span>
            </span>
            <span className={cn(LINE, 'text-[12px] text-muted-foreground')}>Always</span>
        </div>
    );
}

/** An app's events as the integration takes them (each one's description and filters); "Required." marks the filters
 *  it needs. */
export function useEventFilters(integration: string | undefined, event: string | undefined) {
    return useIntegrationEvents(event ? integration : undefined);
}

/** Every event an app's integration has, each with its description and filters. */
export function useIntegrationEvents(integration: string | undefined) {
    return useWorkV1(integration ? `work:events:${integration}` : null, async (client) => {
        const page = await client.request<{ data: JsonObject[] }>('GET', `/v1/integrations/${encodeURIComponent(integration!)}/events`);
        return page.data;
    });
}

/** A chosen way's setup in place: Connect when its app isn't connected, then its own filters. */
function Setup({ wake, onChange }: { wake: Wake; onChange: (w: Wake) => void }) {
    const client = useWorkClient();
    const connections = useAppConnections();
    const filters = useEventFilters(wake.integration, wake.event);
    const [connecting, setConnecting] = useState(false);
    const b = BUILT_INS.find((x) => x.key === wake.key);
    if (b)
        return b.choices ? (
            <div className="flex flex-wrap gap-1.5">
                {b.choices.map((c) => (
                    <button key={c.value} type="button" onClick={() => onChange({ ...wake, settings: { choice: c.value } })} className={cn(CHIP, wake.settings.choice === c.value ? CHIP_ON : CHIP_OFF)}>
                        {c.label}
                    </button>
                ))}
            </div>
        ) : (
            <span className={NOTE}>{b.builtin === 'inbox' ? 'Its address is made with it, named after it.' : 'Its URL shows on its profile once it’s made.'}</span>
        );
    if (!wake.integration) return null;
    const connection = connections.get(wake.integration);
    const connect = async () => {
        setConnecting(true);
        // Opened before the call, so the browser lets the tab open.
        const tab = openTabForLater();
        try {
            const made = connection ?? (await Connection.create(wake.integration!, { client, integration: wake.integration, allowExisting: true }));
            tab.go(made.connectUrl ?? (await made.request()).url);
            rereadAccounts();
        } catch (error) {
            tab.close();
            toast(`Couldn’t connect ${wake.app}`, { description: error instanceof Error ? error.message : String(error) });
        } finally {
            setConnecting(false);
        }
    };
    if (!connection?.connected)
        return (
            <div className="flex flex-wrap items-center gap-2">
                <button type="button" disabled={connecting} onClick={() => void connect()} className={cn(CHIP, CHIP_OFF, 'h-8 px-3')}>
                    <AppMark nodeType={wake.nodeType ?? catalogApp(wake.integration).nodeType} className="h-3.5 w-3.5" />
                    Connect {wake.app}
                </button>
                <span className={NOTE}>It listens once it’s connected.</span>
            </div>
        );
    const own = filters.data?.find((e) => e.name === wake.event);
    const fields = Object.entries((own?.filters ?? {}) as Record<string, string>);
    if (!fields.length) return <span className={NOTE}>Nothing to set: every {wake.label.toLowerCase()} in your {wake.app} wakes it.</span>;
    return (
        <div className="flex flex-col gap-2">
            {fields.map(([name, about]) => {
                const required = /^required\.?/i.test(about);
                const hint = about.replace(/^required\.?\s*/i, '');
                return (
                    <label key={name} className="block">
                        <span className="block pb-1 text-[12px] text-muted-foreground">
                            {eventWords(name)}
                            {!required && ' · optional'}
                        </span>
                        <input
                            value={wake.settings[name] ?? ''}
                            onChange={(e) => onChange({ ...wake, settings: { ...wake.settings, [name]: e.target.value } })}
                            placeholder={hint.slice(0, 48)}
                            aria-label={eventWords(name)}
                            className="h-8 w-full rounded-full bg-foreground/[0.05] px-3 text-[13px] outline-none placeholder:text-[hsl(var(--placeholder))] focus:bg-foreground/[0.08]"
                        />
                    </label>
                );
            })}
        </div>
    );
}

/** The chosen ways, each removable, with its setup open under it. */
function Chosen({ value, onChange, open, setOpen }: { value: Wake[]; onChange: (v: Wake[]) => void; open: string | null; setOpen: (k: string | null) => void }) {
    const connections = useAppConnections();
    if (!value.length) return null;
    return (
        <div className="flex flex-col">
            {value.map((w) => (
                <div key={w.key} className={cn('rounded-xl', open === w.key && 'bg-foreground/[0.03]')}>
                    <div className="flex items-start gap-2.5 px-2.5 py-2 text-[13.5px] leading-5">
                        <span className={LINE}>
                            <WakeMark wake={w} />
                        </span>
                        <button type="button" onClick={() => setOpen(open === w.key ? null : w.key)} className="min-w-0 flex-1 text-left">
                            <span className="block">
                                {wakeTitle(w)}
                                {w.integration && !connections.get(w.integration)?.connected && <span className="ml-1.5 text-[12px] text-muted-foreground">· not connected</span>}
                            </span>
                            {w.why && <span className={NOTE}>Because {w.why}</span>}
                        </button>
                        <button type="button" aria-label={`Remove ${wakeTitle(w)}`} onClick={() => onChange(value.filter((x) => x.key !== w.key))} className="-my-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full text-muted-foreground hover:bg-foreground/[0.08] hover:text-foreground">
                            <X className="h-3.5 w-3.5" />
                        </button>
                    </div>
                    {open === w.key && (
                        <div className="pb-2.5 pl-[36px] pr-2.5">
                            <Setup wake={w} onChange={(n) => onChange(value.map((x) => (x.key === n.key ? n : x)))} />
                        </div>
                    )}
                </div>
            ))}
        </div>
    );
}

const PER_APP = 3;
const MAX_APPS = 6;
/** "1 event", "3 events": a count with its noun, singular for one. */
const count = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;
const countEvents = (n: number) => count(n, 'event');

/** One search over every event: grouped by app, three each, "Show all N"; empty, the built-ins and your connected apps. */
function EventSearch({ value, onPick }: { value: Wake[]; onPick: (w: Wake) => void }) {
    const apps = useEventApps();
    const connections = useAppConnections();
    const [q, setQ] = useState('');
    const [all, setAll] = useState<string | null>(null);
    const input = useRef<HTMLInputElement>(null);
    useEffect(() => input.current?.focus(), []);
    const picked = (k: string) => value.some((w) => w.key === k);
    const terms = q.trim().toLowerCase().split(/\s+/).filter(Boolean);
    const list = apps.data ?? [];
    const groups = useMemo(() => {
        if (!terms.length) return [];
        return list
            .filter((a) => !all || a.integration === all)
            .map((a) => ({ app: a, events: a.events.filter((e) => terms.every((t) => `${a.label} ${e.label} ${e.name}`.toLowerCase().includes(t))) }))
            .filter((g) => g.events.length);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [q, all, list]);
    const allApp = all ? list.find((a) => a.integration === all) : null;
    const eventRow = (app: EventApp, e: EventApp['events'][number], withApp = true) => {
        const key = `${app.integration}:${e.name}`;
        return (
            <button key={key} type="button" onClick={() => onPick(fromEvent(app, e))} className={ROW}>
                <span className={LINE}>
                    <AppMark nodeType={app.nodeType} />
                </span>
                <span className="min-w-0 flex-1">
                    {withApp && <span className="text-muted-foreground">{app.label} · </span>}
                    {e.label}
                </span>
                {picked(key) ? (
                    <span className={LINE}>
                        <Check className="h-4 w-4" />
                    </span>
                ) : (
                    !connections.get(app.integration)?.connected && <span className={cn(LINE, 'text-[11.5px] text-muted-foreground')}>Connect</span>
                )}
            </button>
        );
    };
    const appRow = (app: EventApp) => (
        <button key={app.integration} type="button" onClick={() => setAll(app.integration)} className={cn(ROW, 'items-center')}>
            <AppMark nodeType={app.nodeType} />
            <span className="min-w-0 flex-1">{app.label}</span>
            <span className="text-[12px] tabular-nums text-muted-foreground">{countEvents(app.events.length)}</span>
            <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" strokeWidth={2} />
        </button>
    );
    const total = list.reduce((n, a) => n + a.events.length, 0);
    const connectedApps = list.filter((a) => connections.get(a.integration)?.connected);
    return (
        <div className="flex min-h-0 flex-1 flex-col">
            <label className="mx-1 flex shrink-0 items-center gap-2 rounded-full bg-foreground/[0.05] px-3 focus-within:bg-foreground/[0.08]">
                {allApp ? (
                    <button type="button" aria-label="All apps" onClick={() => setAll(null)} className="-ml-1 grid h-6 w-6 place-items-center rounded-full hover:bg-foreground/[0.08]">
                        <ArrowLeft className="h-3.5 w-3.5" />
                    </button>
                ) : (
                    <Search className="h-4 w-4 shrink-0 text-muted-foreground" strokeWidth={1.75} />
                )}
                <input
                    value={q}
                    ref={input}
                    onChange={(e) => setQ(e.target.value)}
                    placeholder={allApp ? `Search ${count(allApp.events.length, `${allApp.label} event`)}` : `Search ${countEvents(total)} in ${count(list.length, 'app')}`}
                    aria-label="Search events"
                    className="h-9 min-w-0 flex-1 bg-transparent text-[13.5px] outline-none placeholder:text-[hsl(var(--placeholder))]"
                />
            </label>
            {/* Only the list scrolls: the search above it stays put. */}
            <div className="mt-1 min-h-0 flex-1 overflow-y-auto scrollbar-subtle" data-testid="wake-list">
                {!apps.data && <p className={cn(LABEL, 'py-4')}>{apps.error !== undefined ? 'Couldn’t load the apps.' : 'Loading every app’s events…'}</p>}
                {apps.data && allApp && !terms.length && (
                    <>
                        <p className={LABEL}>{allApp.events.length === 1 ? `1 ${allApp.label} event` : `All ${allApp.events.length} ${allApp.label} events`}</p>
                        {allApp.events.map((e) => eventRow(allApp, e, false))}
                    </>
                )}
                {apps.data && !allApp && !terms.length && (
                    <>
                        <p className={LABEL}>Built in</p>
                        <div className="flex flex-wrap gap-1.5 px-2.5 pb-1.5">
                            {BUILT_INS.map((b) => {
                                const Icon = BUILT_IN_ICON[b.builtin];
                                return (
                                    <ShortcutTooltip key={b.key} label={b.detail}>
                                        <button type="button" onClick={() => onPick(fromBuiltIn(b))} className={cn(CHIP, picked(b.key) ? CHIP_ON : CHIP_OFF)}>
                                            <Icon className="h-3.5 w-3.5" strokeWidth={1.75} />
                                            {b.label}
                                        </button>
                                    </ShortcutTooltip>
                                );
                            })}
                        </div>
                        {connectedApps.length > 0 && (
                            <>
                                <p className={LABEL}>Your connected apps</p>
                                {connectedApps.map(appRow)}
                            </>
                        )}
                        <p className={cn(LABEL, 'pb-2')}>
                            {list.length === 1 ? `Or search its ${countEvents(total)}.` : `Or search all ${list.length} apps and their ${countEvents(total)}.`}
                        </p>
                    </>
                )}
                {apps.data && terms.length > 0 && !groups.length && <p className={cn(LABEL, 'py-3')}>No event matches “{q.trim()}”.</p>}
                {apps.data &&
                    terms.length > 0 &&
                    (allApp
                        ? groups.flatMap((g) => g.events.map((e) => eventRow(g.app, e, false)))
                        : groups.slice(0, MAX_APPS).flatMap((g) => [
                              ...g.events.slice(0, PER_APP).map((e) => eventRow(g.app, e)),
                              ...(g.events.length > PER_APP
                                  ? [
                                        <button key={`${g.app.integration}:all`} type="button" onClick={() => setAll(g.app.integration)} className="ml-[36px] rounded-full px-1 pb-1 text-left text-[12px] text-muted-foreground hover:text-foreground">
                                            Show all {g.events.length} {g.app.label} matches ›
                                        </button>,
                                    ]
                                  : []),
                          ]))}
                {apps.data && terms.length > 0 && !allApp && groups.length > MAX_APPS && <p className={cn(LABEL, 'pb-2')}>And {count(groups.length - MAX_APPS, 'more app', 'more apps')}: keep typing.</p>}
            </div>
        </div>
    );
}

/** The popup: messages always, what's chosen with its setup, then "Add another", which searches every event. */
export function WakesBody({ value, onChange }: { value: Wake[]; onChange: (v: Wake[]) => void }) {
    const [open, setOpen] = useState<string | null>(value[0]?.key ?? null);
    const [adding, setAdding] = useState(false);
    const pick = (w: Wake) => {
        if (!value.some((x) => x.key === w.key)) onChange([...value, w]);
        setOpen(w.key);
        setAdding(false);
    };
    return (
        <div className="flex min-h-0 flex-1 flex-col">
            <AlwaysRow />
            <p className={LABEL}>From its job</p>
            {value.length ? <Chosen value={value} onChange={onChange} open={open} setOpen={setOpen} /> : <p className={cn(NOTE, 'px-2.5 pb-2')}>Nothing in its job says what else should wake it.</p>}
            {adding ? (
                <div className="flex min-h-0 flex-1 flex-col pt-1">
                    <EventSearch value={value} onPick={pick} />
                </div>
            ) : (
                <button type="button" onClick={() => setAdding(true)} className={cn(ROW, 'items-center text-muted-foreground hover:text-foreground')}>
                    <Plus className="h-4 w-4 shrink-0" strokeWidth={2} />
                    Add another
                </button>
            )}
        </div>
    );
}
