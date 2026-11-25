// One trigger opened in its row: its whole sentence, what stopped it and the fix, its own setup (changed in place
// where its view takes `update`: a schedule's time, an app event's filters, a channel's mode, what it does then), then
// Try it now, Pause or Resume, and Remove. What's changed where it lives (its inbox, its number, an automation's step,
// what it set itself) says so.
import { useState } from 'react';
import { CircleAlert, Pause, Play, Trash2, Workflow } from 'lucide-react';
import { Cron, type JsonObject, type TriggerChanges } from 'noclick';
import { BUTTON_GHOST, BUTTON_PRIMARY, BUTTON_SECONDARY } from '@/ui/buttons';
import { cn } from '@/ui/utils';
import { eventLabel, platformEvent, readSchedule, sentenceOf, whenOf, type Names, type TriggerItem } from './model';
import { useEventDetails, useIntegrationOf, type TriggerActions } from './data';
import { Copyable, LABEL, NOTE, Pills, ScheduleField, ThenField, localZone } from './parts';

const str = (v: unknown) => (typeof v === 'string' ? v : '');
/** The kinds whose `message` a person changes here. */
const TOLD = new Set(['cron', 'webhook', 'event', 'platform', 'queue']);

export function TriggerDetails({ item, names, actions, agentName }: { item: TriggerItem; names: Names; actions: TriggerActions; agentName: string }) {
    const s = item.spec;
    const can = (a: TriggerItem['actions'][number]) => item.actions.includes(a);
    const editable = can('update');
    const [words, setWords] = useState('');
    // Its clock as the field shows it: `user` (its agent's user's) and none read as yours.
    const shownTz = str(s.tz) && str(s.tz) !== 'user' ? str(s.tz) : localZone();
    const [tz, setTz] = useState(shownTz);
    const [message, setMessage] = useState(str(s.message));
    const [filters, setFilters] = useState<Record<string, string>>(() => Object.fromEntries(Object.entries((s.filters ?? {}) as Record<string, unknown>).map(([k, v]) => [k, String(v)])));
    const integrationOf = useIntegrationOf();
    const event = useEventDetails(item.kind === 'event' ? integrationOf(str(s.connection)) : undefined, item.kind === 'event' ? str(s.event) : undefined);
    // Every filter the event takes, and any set that it no longer lists.
    const filterFields = [...(event?.filters ?? []).map((f) => f.name), ...Object.keys(filters).filter((k) => !event?.filters.some((f) => f.name === k))];
    const [saving, setSaving] = useState(false);
    const schedule = item.kind === 'cron' ? readSchedule(words) : null;
    const changes: TriggerChanges = {};
    // A clock left as it was keeps what it was set to.
    const keptTz = tz === shownTz ? str(s.tz) || undefined : tz;
    if (schedule) changes.cron = new Cron(schedule.expr, { tz: keptTz });
    else if (item.kind === 'cron' && tz !== shownTz) changes.cron = new Cron(str(s.cron), { tz });
    if (TOLD.has(item.kind) && message.trim() !== str(s.message)) changes.message = message.trim() || null;
    const filtersNow = Object.fromEntries(Object.entries(filters).filter(([, v]) => v.trim()));
    if (item.kind === 'event' && JSON.stringify(filtersNow) !== JSON.stringify(Object.fromEntries(Object.entries((s.filters ?? {}) as Record<string, unknown>).filter(([, v]) => String(v).trim())))) changes.filters = filtersNow as JsonObject;
    const dirty = Object.keys(changes).length > 0;
    const save = async () => {
        setSaving(true);
        if (await actions.update(item, changes)) setWords('');
        setSaving(false);
    };

    return (
        <div className="flex flex-col gap-3" data-testid="trigger-details">
            <p className="text-[13px] leading-snug text-foreground/80">“{sentenceOf(item, names)}”</p>
            {item.state !== 'live' && item.reason && (
                <div
                    data-testid="trigger-reason"
                    className={cn(
                        'flex flex-wrap items-center gap-2 rounded-xl px-3 py-2 text-[12.5px]',
                        item.state === 'stopped' ? 'bg-red-500/[0.08] text-red-700 dark:text-red-300' : 'bg-foreground/[0.05] text-foreground/80'
                    )}
                >
                    {item.state === 'stopped' ? <CircleAlert className="h-3.5 w-3.5 shrink-0" strokeWidth={2} /> : <Pause className="h-3.5 w-3.5 shrink-0" strokeWidth={2} />}
                    <span className="min-w-0 flex-1">{item.reason}</span>
                    {/* Resuming it is the buttons' own Resume below. */}
                    {actions.label(item) && !(item.fix?.action === 'resume' && can('resume')) && (
                        <button type="button" onClick={() => actions.fix(item)} className={cn(BUTTON_PRIMARY, 'h-7 px-3 text-[12px]')}>
                            {actions.label(item)}
                        </button>
                    )}
                </div>
            )}
            {item.kind === 'cron' &&
                (editable ? (
                    <div>
                        <p className="mb-2 text-[12.5px] text-muted-foreground">Now: {whenOf(item, names)}</p>
                        <ScheduleField words={words} onWords={setWords} tz={tz} onTz={setTz} />
                    </div>
                ) : (
                    <p className="text-[12.5px] text-muted-foreground">{whenOf(item, names)}</p>
                ))}
            {item.kind === 'event' && (
                <div className="flex flex-col gap-2">
                    <p className="text-[12.5px] text-muted-foreground">
                        {item.summary?.app ?? names.appOf(str(s.connection))} · {eventLabel(str(s.event))} · through{' '}
                        {item.summary?.account ? (
                            <span className="text-foreground/85">{item.summary.account}</span>
                        ) : str(s.connection).startsWith('credential:') ? (
                            'your account connected in the app'
                        ) : (
                            <>
                                your <span className="text-foreground/85">{str(s.connection)}</span> account
                            </>
                        )}
                    </p>
                    {filterFields.map((name) => (
                            <label key={name} className="block">
                                <span className={LABEL}>{eventLabel(name)}</span>
                                <input
                                    value={filters[name] ?? ''}
                                    disabled={!editable}
                                    onChange={(e) => setFilters((f) => ({ ...f, [name]: e.target.value }))}
                                    placeholder={`Any ${eventLabel(name).toLowerCase()}`}
                                    aria-label={eventLabel(name)}
                                    className="h-9 w-full rounded-full bg-foreground/[0.05] px-3.5 text-[13.5px] outline-none placeholder:text-[hsl(var(--placeholder))] focus:bg-foreground/[0.08] disabled:opacity-60 max-sm:text-[16px]"
                                />
                            </label>
                        ))}
                </div>
            )}
            {item.kind === 'webhook' && item.url && (
                <div>
                    <span className={LABEL}>Its URL</span>
                    <Copyable value={item.url} label="Its URL" />
                    <p className={NOTE}>The URL is the key: anything that posts to it triggers {agentName}, so share it like one.</p>
                </div>
            )}
            {item.kind === 'email' && (
                <div>
                    <span className={LABEL}>Its address</span>
                    <Copyable value={str(s.address)} label="Its address" />
                    <p className={NOTE}>Who can email it is set on its inbox.</p>
                </div>
            )}
            {item.kind === 'call' && <p className="text-[12.5px] text-muted-foreground">Calls to {str(s.number)} ring it. Change that on the number, in Resources.</p>}
            {item.kind === 'channel' && (
                <div>
                    <span className={LABEL}>In #{str(s.name)}, agents answer</span>
                    <Pills
                        value={str(s.mode) === 'all' ? 'all' : 'mentions'}
                        disabled={!editable}
                        options={[
                            { id: 'mentions', label: '@mentions only' },
                            { id: 'all', label: 'Every message' },
                        ]}
                        onChange={(mode) => mode !== str(s.mode) && void actions.update(item, { mode })}
                    />
                    <p className={NOTE}>It’s #{str(s.name)}’s own setting, so it applies to every agent there. Changing it needs the right to manage the channel.</p>
                </div>
            )}
            {item.kind === 'platform' && <p className="text-[12.5px] text-muted-foreground">{platformEvent(str(s.type))?.detail ?? str(s.type)}</p>}
            {item.kind === 'app' && <p className="text-[12.5px] text-muted-foreground">It’s a step of an automation. Change it there.</p>}
            {(item.kind === 'routine' || item.kind === 'wakeup') && (
                <p className="text-[12.5px] text-muted-foreground">
                    {item.setBy === 'agent' ? 'It set this itself' : 'You set this'}
                    {str(s.conversation) ? `, from your conversation “${str(s.conversation)}”` : ''}.
                </p>
            )}
            {TOLD.has(item.kind) && editable && <ThenField label="What it does then" value={message} onChange={setMessage} placeholder="Read what came in and act on it" />}
            <div className="flex flex-wrap items-center gap-1.5">
                {dirty && (
                    <button type="button" disabled={saving} onClick={() => void save()} className={cn(BUTTON_PRIMARY, 'h-8 px-3.5 text-[12.5px]')}>
                        {saving ? 'Saving…' : 'Save changes'}
                    </button>
                )}
                {can('test') && item.state === 'live' && (
                    <button type="button" onClick={() => actions.test(item)} className={cn(BUTTON_SECONDARY, 'h-8 px-3 text-[12.5px]')}>
                        <Play className="h-3.5 w-3.5" strokeWidth={2} />
                        Try it now
                    </button>
                )}
                {can('resume') ? (
                    <button type="button" onClick={() => actions.resume(item)} className={cn(BUTTON_GHOST, 'h-8 px-3 text-[12.5px]')}>
                        <Play className="h-3.5 w-3.5" strokeWidth={2} />
                        Resume
                    </button>
                ) : (
                    can('pause') && (
                        <button type="button" onClick={() => actions.pause(item)} className={cn(BUTTON_GHOST, 'h-8 px-3 text-[12.5px]')}>
                            <Pause className="h-3.5 w-3.5" strokeWidth={2} />
                            Pause
                        </button>
                    )
                )}
                {item.kind === 'app' && (
                    <button type="button" onClick={() => actions.fix({ ...item, fix: { action: 'open_in_app' } })} className={cn(BUTTON_SECONDARY, 'h-8 px-3 text-[12.5px]')}>
                        <Workflow className="h-3.5 w-3.5" strokeWidth={2} />
                        Open in the app
                    </button>
                )}
                {(can('remove') || can('cancel')) && (
                    <button type="button" onClick={() => actions.remove(item)} className="ml-auto inline-flex h-8 items-center gap-1.5 rounded-full px-3 text-[12.5px] text-red-600 transition-colors hover:bg-red-500/10 dark:text-red-400">
                        <Trash2 className="h-3.5 w-3.5" strokeWidth={2} />
                        {can('cancel') ? 'Cancel it' : 'Remove'}
                    </button>
                )}
            </div>
        </div>
    );
}
