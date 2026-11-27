// Settings > Webhooks: the endpoints events are delivered to (the account's and its users'),
// each with its health; the lab reads the same page from fixtures. The drawer
// (`?webhook=`) edits what an endpoint receives, pauses it, rotates its secret, sends a
// test event and lists its deliveries; `&delivery=` opens one with the request sent and
// the response that came back, and redelivers it.
import { useMemo, useState, type ReactNode } from 'react';
import { ArrowLeft, Bell, RotateCw, Terminal } from 'lucide-react';
import { Link } from 'react-router';
import { toast } from 'sonner';
import { HAIRLINE, ROW_HOVER, clickableRow } from '@/ui/primitives';
import { cn } from '@/ui/utils';
import { FieldSelect } from '@/ui/FieldSelect';
import { Event as NoClickEvent, Webhook, type EventType, type WebhookDelivery } from 'noclick';
import { formatCount, formatDuration, formatRelative } from '@/screens/console/lib/format';
import { NEW_SNIPPETS, type Snippet } from '@/screens/console/lib/snippets';
import type { StatusLook } from '@/screens/console/lib/status';
import { defaultWriteUser } from '@/screens/console/lib/userFilter';
import { useConsole, useConsoleHref } from '@/screens/console/hooks/useConsole';
import { usePaged } from '@/sdk/usePaged';
import { useSearchParam, useUserParam } from '@/screens/console/hooks/useQueryState';
import { invalidateV1, useV1 } from '@/sdk/useV1';
import { ConsoleButton } from '../ui/Button';
import { CodeSnippet } from '../ui/CodeSnippet';
import { ConsoleDialog } from '../ui/ConsoleDialog';
import { CopyButton } from '../ui/CopyButton';
import { DataTable, type Column } from '../ui/DataTable';
import { Drawer } from '../ui/Drawer';
import { EmptyCode } from '../ui/EmptyCode';
import { ErrorPanel } from '../ui/ErrorPanel';
import { JsonView } from '../ui/JsonView';
import { PageHeader } from '../ui/PageHeader';
import { RevealOnceSecret } from '../ui/RevealOnceSecret';
import { Segmented } from '../ui/Segmented';
import { StatusPill } from '../ui/StatusPill';
import { SWITCH_ROWS, SwitchRow } from '../ui/SwitchRow';
import { TimeCell } from '../ui/TimeCell';
import { NewInCode } from '../NewInCode';
import { ConfirmAction, errorText, Field, PanelToolbar, Section } from './resources/shared';

// ── what the page says in code ─────────────────────────────────────────────

/** The receiver's side, reading the secret from the environment. */
export const WEBHOOK_VERIFY: Snippet = {
    python: [
        'import os',
        'import noclick',
        '',
        '# in your POST handler, with the raw body and headers',
        'event = noclick.Webhook.verify(body, headers, os.environ["NOCLICK_WEBHOOK_SECRET"])',
        'print(event.type, event.data)',
    ].join('\n'),
    typescript: [
        'import { Webhook } from "noclick";',
        '',
        '// in your POST handler, with the raw body and headers',
        'const event = await Webhook.verify(await request.text(), request.headers, process.env.NOCLICK_WEBHOOK_SECRET!);',
        'console.log(event.type, event.data);',
    ].join('\n'),
};

export const LISTEN_COMMAND = 'noclick webhooks listen --forward-to http://localhost:3000/noclick/events';

// ── event types ────────────────────────────────────────────────────────────

/** Areas in the order the picker lists them; an area is the part of a type before its first dot. */
const AREA_GROUPS: readonly { label: string; areas: readonly string[] }[] = [
    { label: 'Operations', areas: ['operation'] },
    { label: 'People', areas: ['human'] },
    { label: 'Agents', areas: ['agent'] },
    { label: 'Connections', areas: ['connection'] },
    { label: 'Inboxes and calls', areas: ['inbox', 'phone'] },
    { label: 'Channels and sandboxes', areas: ['channel', 'sandbox'] },
    { label: 'Apps', areas: ['deployment', 'schedule', 'database'] },
    { label: 'Domains', areas: ['domain'] },
    { label: 'Cards and spend', areas: ['card', 'spend', 'usage', 'user'] },
];

export interface EventGroup {
    label: string;
    areas: string[];
    types: EventType[];
}

/** The catalog grouped for the picker; an area this list doesn't know yet gets a group of its own. */
export function groupEventTypes(types: readonly EventType[]): EventGroup[] {
    const known = new Set(AREA_GROUPS.flatMap((g) => g.areas));
    const groups: EventGroup[] = AREA_GROUPS.map((g) => ({ label: g.label, areas: [...g.areas], types: types.filter((t) => g.areas.includes(t.area)) }));
    for (const area of [...new Set(types.map((t) => t.area))].filter((a) => !known.has(a))) {
        groups.push({ label: area.charAt(0).toUpperCase() + area.slice(1), areas: [area], types: types.filter((t) => t.area === area) });
    }
    return groups.filter((g) => g.types.length);
}

/** Whether `pattern` (`operation.*`, `*`, or a type) takes `type`. */
export function patternMatches(pattern: string, type: string): boolean {
    if (pattern === '*') return true;
    return pattern.endsWith('.*') ? type.startsWith(pattern.slice(0, -1)) : pattern === type;
}

const covered = (patterns: readonly string[], type: string) => patterns.some((p) => patternMatches(p, type));
const wildcard = (area: string) => `${area}.*`;

/**
 * The patterns after ticking or unticking one type or one group. Unticking a
 * type a wildcard covers spells the wildcard out, so the rest stay selected.
 */
export function togglePatterns(patterns: readonly string[], groups: readonly EventGroup[], target: { type: string } | { group: EventGroup }, on: boolean): string[] {
    const all = groups.flatMap((g) => g.types.map((t) => t.name));
    // `*` spelled out as each group's wildcards, so one part of it can come off.
    let next = patterns.includes('*') ? groups.flatMap((g) => g.areas.map(wildcard)) : [...patterns];
    if ('group' in target) {
        const { areas, types } = target.group;
        next = next.filter((p) => !areas.some((a) => p === wildcard(a)) && !types.some((t) => t.name === p));
        if (on) next.push(...areas.map(wildcard));
    } else {
        const area = target.type.split('.')[0];
        if (on) {
            if (!covered(next, target.type)) next.push(target.type);
        } else if (next.includes(wildcard(area))) {
            next = next.filter((p) => p !== wildcard(area));
            next.push(...all.filter((name) => name.split('.')[0] === area && name !== target.type && !covered(next, name)));
        } else {
            next = next.filter((p) => p !== target.type);
        }
        // Ticking the last type of a group ticks the group.
        const group = groups.find((g) => g.types.some((t) => t.name === target.type));
        if (on && group && group.types.every((t) => covered(next, t.name))) {
            next = next.filter((p) => !group.types.some((t) => t.name === p) && !group.areas.some((a) => p === wildcard(a)));
            next.push(...group.areas.map(wildcard));
        }
    }
    // Every type chosen is every event, including types added later.
    return all.length && all.every((name) => covered(next, name)) && groups.every((g) => g.areas.every((a) => next.includes(wildcard(a)))) ? ['*'] : next;
}

/** What an endpoint receives, as the table and the drawer read it. */
export function EventPatterns({ patterns, max = 2, wrap = false }: { patterns: readonly string[]; max?: number; wrap?: boolean }) {
    if (patterns.includes('*')) return <span className="text-foreground/80">All events</span>;
    const shown = patterns.slice(0, max);
    const rest = patterns.length - shown.length;
    return (
        <span className={cn('inline-flex min-w-0 max-w-full items-center gap-1', wrap ? 'flex-wrap' : 'overflow-hidden')} title={patterns.join(', ')}>
            {shown.map((p) => (
                <span key={p} className="shrink-0 rounded bg-foreground/[0.05] px-1.5 py-[1px] font-mono text-[12px] text-foreground/80">
                    {p}
                </span>
            ))}
            {rest > 0 && <span className="text-[12px] tabular-nums text-muted-foreground">+{rest}</span>}
        </span>
    );
}

export function EventPicker({ types, value, onChange }: { types: readonly EventType[]; value: readonly string[]; onChange: (next: string[]) => void }) {
    const groups = useMemo(() => groupEventTypes(types), [types]);
    const everything = value.includes('*');
    return (
        <div className="flex flex-col gap-3">
            <ul className={SWITCH_ROWS}>
                <li>
                    <SwitchRow label="All events" description="Every type, including ones added later." checked={everything} onCheckedChange={(on) => onChange(on ? ['*'] : [])} />
                </li>
            </ul>
            <div role="group" aria-label="Event types" className="flex flex-col gap-4">
                {groups.map((g) => {
                    const whole = everything || g.areas.every((a) => value.includes(wildcard(a)));
                    return (
                        <section key={g.label} aria-label={g.label}>
                            <h4 className="m-0 text-[13px] font-medium text-foreground">{g.label}</h4>
                            <ul className={SWITCH_ROWS}>
                                <li>
                                    <SwitchRow
                                        label={`All ${g.label.toLowerCase()} events`}
                                        description="Including ones added later."
                                        id={g.areas.map(wildcard).join(' ')}
                                        checked={whole}
                                        disabled={everything}
                                        onCheckedChange={(on) => onChange(togglePatterns(value, groups, { group: g }, on))}
                                    />
                                </li>
                                {g.types.map((t) => (
                                    <li key={t.name}>
                                        <SwitchRow
                                            label={t.description}
                                            description={t.emitted ? undefined : 'Not sent yet.'}
                                            id={t.name}
                                            checked={covered(value, t.name)}
                                            disabled={everything}
                                            onCheckedChange={(on) => onChange(togglePatterns(value, groups, { type: t.name }, on))}
                                        />
                                    </li>
                                ))}
                            </ul>
                        </section>
                    );
                })}
            </div>
        </div>
    );
}

export function useEventTypes() {
    const { client } = useConsole();
    return useV1('events/types', () => NoClickEvent.types({ client }));
}

// ── looks ──────────────────────────────────────────────────────────────────

export function webhookLook(hook: Webhook): StatusLook {
    if (hook.status === 'disabled') return { label: 'Disabled', glyph: 'muted', tone: 'muted' };
    if (hook.status === 'failing') {
        const code = hook.lastFailure?.response_status;
        return { label: 'Failing', reason: typeof code === 'number' ? String(code) : 'no answer', glyph: 'cross', tone: 'failure' };
    }
    return { label: 'Healthy', glyph: 'check', tone: 'ink' };
}

export function deliveryLook(d: WebhookDelivery): StatusLook {
    const code = d.responseStatus === null ? null : String(d.responseStatus);
    switch (d.status) {
        case 'succeeded':
            return { label: 'Delivered', reason: code, glyph: 'check', tone: 'ink' };
        case 'retrying':
            return { label: 'Retrying', reason: code ?? 'no answer', glyph: 'waiting', tone: 'ink' };
        case 'failed':
            return { label: 'Failed', reason: code ?? 'no answer', glyph: 'cross', tone: 'failure' };
        default:
            return { label: 'Pending', glyph: 'hollow', tone: 'ink' };
    }
}

/** `99.8%` (a decimal only near 100, where it matters). */
export function formatRate(rate: number | null): string {
    if (rate === null) return '—';
    const pct = rate * 100;
    return `${pct > 99 && pct < 100 ? pct.toFixed(1) : Math.round(pct)}%`;
}

const plural = (n: number, one: string, many = `${one}s`) => `${formatCount(n)} ${n === 1 ? one : many}`;

// ── one delivery ───────────────────────────────────────────────────────────

/** A drawer section whose heading carries a control on the right. */
function Titled({ title, right, children }: { title: string; right: ReactNode; children: ReactNode }) {
    return (
        <section aria-label={title}>
            <div className="mb-2 flex min-h-8 items-center justify-between gap-2">
                <h3 className="m-0 text-[14px] font-semibold tracking-[-0.01em] text-foreground">{title}</h3>
                {right}
            </div>
            {children}
        </section>
    );
}

function Pre({ children }: { children: ReactNode }) {
    return (
        <pre className="m-0 max-h-[280px] overflow-auto whitespace-pre-wrap break-all rounded-xl bg-foreground/[0.04] px-3.5 py-3 font-mono text-[12px] leading-relaxed text-foreground/90 dark:bg-foreground/[0.05]">
            {children}
        </pre>
    );
}

function parsed(text: string | null): unknown {
    if (!text) return undefined;
    try {
        return JSON.parse(text);
    } catch {
        return undefined;
    }
}

/** A delivery in full: the event it carried, each attempt's outcome, the request and the response. */
export function DeliveryView({ hook, delivery, onBack, onRedelivered }: { hook: Webhook; delivery: WebhookDelivery; onBack?: () => void; onRedelivered?: (d: WebhookDelivery) => void }) {
    const { now } = useConsole();
    const href = useConsoleHref();
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const request = parsed(delivery.requestBody);
    const response = parsed(delivery.responseBody);
    const redeliver = async () => {
        setBusy(true);
        setError(null);
        try {
            const next = await hook.redeliver(delivery);
            invalidateV1(`webhooks/${hook.id}/deliveries`);
            invalidateV1('events/');
            toast(next.ok ? `Redelivered: ${next.responseStatus ?? 'ok'}` : `Redelivery failed: ${next.responseStatus ?? 'no answer'}`);
            onRedelivered?.(next);
        } catch (e) {
            setError(errorText(e));
        } finally {
            setBusy(false);
        }
    };
    return (
        <div className="flex flex-col gap-5">
            {onBack && (
                <ConsoleButton variant="ghost" size="sm" className="self-start" onClick={onBack} icon={<ArrowLeft className="h-3.5 w-3.5" />}>
                    All deliveries
                </ConsoleButton>
            )}
            <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-mono text-[13px] font-medium text-foreground">{delivery.eventType}</span>
                <StatusPill look={deliveryLook(delivery)} />
            </div>
            <dl className="m-0">
                <Field label="Event">
                    {delivery.eventId ? (
                        <Link to={href('logs/events', { event: delivery.eventId })} className="underline underline-offset-2">
                            {delivery.eventId}
                        </Link>
                    ) : (
                        '—'
                    )}
                </Field>
                <Field label="Sent">
                    <TimeCell value={delivery.createdAt} tier="absolute" />
                </Field>
                <Field label="Attempts">
                    {formatCount(delivery.attempts)}
                    {delivery.nextRetryAt && <span className="text-muted-foreground"> · next retry {formatRelative(delivery.nextRetryAt, now())}</span>}
                </Field>
                <Field label="Response">
                    {delivery.responseStatus ?? <span className="text-muted-foreground">No answer</span>}
                    {delivery.durationMs !== null && <span className="text-muted-foreground"> in {formatDuration(delivery.durationMs)}</span>}
                </Field>
            </dl>
            <Section title={`Request · POST ${hook.url}`}>
                {request !== undefined ? <JsonView value={request} /> : <Pre>{delivery.requestBody ?? '(empty)'}</Pre>}
                <p className="m-0 mt-1.5 text-[12px] text-muted-foreground">
                    Signed in the <span className="font-mono">NoClick-Signature</span> header with this endpoint&apos;s secret.
                </p>
            </Section>
            <Section title={`Response${delivery.responseStatus !== null ? ` · ${delivery.responseStatus}` : ''}`}>
                {response !== undefined ? <JsonView value={response} /> : delivery.responseBody ? <Pre>{delivery.responseBody}</Pre> : <p className="m-0 text-[13px] text-muted-foreground">No body.</p>}
            </Section>
            <div className="flex flex-wrap items-center gap-2">
                <ConsoleButton disabled={busy} onClick={() => void redeliver()}>
                    {busy ? 'Redelivering…' : 'Redeliver'}
                </ConsoleButton>
                <span className="text-[12px] text-muted-foreground">Sends the same event again now, with the same id.</span>
                {error && <span className="text-[12px] text-red-600 dark:text-red-400">{error}</span>}
            </div>
        </div>
    );
}

/** Deliveries as rows: when, which event, how it went. */
export function DeliveryRows({ rows, onOpen, showEvent = true, hookUrl }: { rows: readonly WebhookDelivery[]; onOpen: (d: WebhookDelivery) => void; showEvent?: boolean; hookUrl?: (d: WebhookDelivery) => string }) {
    return (
        <ul aria-label="Deliveries" className={'m-0 -mx-3 list-none p-0'}>
            {rows.map((d) => (
                <li key={d.id} className={cn('flex cursor-pointer items-center gap-3 px-3 py-2 text-[13px]', ROW_HOVER)} {...clickableRow(() => onOpen(d))}>
                    <TimeCell value={d.createdAt} className="w-16 shrink-0 text-[12px] text-muted-foreground" />
                    <span className="min-w-0 flex-1 truncate font-mono text-[12px]">{showEvent ? d.eventType : hookUrl?.(d)}</span>
                    <span className="hidden w-20 shrink-0 text-right text-[12px] tabular-nums text-muted-foreground sm:inline">{plural(d.attempts, 'attempt')}</span>
                    <StatusPill look={deliveryLook(d)} className="shrink-0 sm:w-[8.5rem] sm:justify-end" />
                </li>
            ))}
        </ul>
    );
}

// ── the drawer ─────────────────────────────────────────────────────────────

function EditEventsDialog({ hook, onClose }: { hook: Webhook; onClose: () => void }) {
    const types = useEventTypes();
    const [events, setEvents] = useState<string[]>(hook.events);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>(undefined);
    const save = async () => {
        setBusy(true);
        setError(undefined);
        try {
            await hook.update({ events });
            invalidateV1('webhooks');
            toast('Events updated');
            onClose();
        } catch (e) {
            setError(e);
        } finally {
            setBusy(false);
        }
    };
    return (
        <ConsoleDialog
            open
            onOpenChange={(o) => !o && onClose()}
            size="lg"
            mark={<Bell aria-hidden className="h-5 w-5" />}
            title="Events this endpoint receives"
            description="NoClick POSTs each of them here, signed, as it happens."
            footer={
                <>
                    <ConsoleButton variant="ghost" onClick={onClose}>
                        Cancel
                    </ConsoleButton>
                    <ConsoleButton variant="primary" disabled={busy || !events.length} onClick={() => void save()}>
                        Save
                    </ConsoleButton>
                </>
            }
        >
            {types.error !== undefined && <ErrorPanel error={types.error} onRetry={() => void types.refresh()} />}
            {types.data ? <EventPicker types={types.data} value={events} onChange={setEvents} /> : types.error === undefined && <div aria-busy className="h-48 animate-pulse rounded-lg bg-foreground/[0.04]" />}
            {error !== undefined && <ErrorPanel error={error} className="mt-3" />}
        </ConsoleDialog>
    );
}

function SendTest({ hook }: { hook: Webhook }) {
    const types = useEventTypes();
    const options = types.data?.filter((t) => covered(hook.events, t.name)) ?? [];
    const [type, setType] = useState('');
    const [busy, setBusy] = useState(false);
    const [result, setResult] = useState<WebhookDelivery | null>(null);
    const [error, setError] = useState<string | null>(null);
    const chosen = type || options[0]?.name || '';
    const send = async () => {
        setBusy(true);
        setError(null);
        setResult(null);
        try {
            setResult(await hook.test(chosen));
        } catch (e) {
            setError(errorText(e));
        } finally {
            setBusy(false);
        }
    };
    return (
        <Section title="Send a test event">
            <div className="flex flex-wrap items-center gap-2">
                <FieldSelect
                    aria-label="Test event type"
                    className="w-auto min-w-[14rem] max-w-full"
                    value={chosen}
                    onValueChange={setType}
                    options={options.map((t) => ({ value: t.name, label: <>{t.description} <span className="font-mono text-[11.5px] text-muted-foreground">{t.name}</span></> }))}
                />
                <ConsoleButton disabled={busy || !chosen} onClick={() => void send()}>
                    {busy ? 'Sending…' : 'Send test'}
                </ConsoleButton>
            </div>
            {result && (
                <p className="m-0 mt-2 flex flex-wrap items-center gap-2 text-[13px]">
                    <StatusPill look={deliveryLook(result)} />
                    <span className="text-muted-foreground">
                        {result.ok ? 'Your server accepted it' : 'Your server refused it'}
                        {result.durationMs !== null && ` in ${formatDuration(result.durationMs)}`}. Test events aren&apos;t retried.
                    </span>
                </p>
            )}
            {error && <p className="m-0 mt-2 text-[12px] text-red-600 dark:text-red-400">{error}</p>}
        </Section>
    );
}

const DELIVERY_VIEWS = [
    { value: 'all', label: 'All' },
    { value: 'failing', label: 'Failing' },
] as const;

function Deliveries({ hook, onOpen }: { hook: Webhook; onOpen: (d: WebhookDelivery) => void }) {
    const [view, setView] = useState<'all' | 'failing'>('all');
    const status = view === 'failing' ? (['retrying', 'failed'] as const) : undefined;
    const deliveries = useV1(`webhooks/${hook.id}/deliveries?${view}`, () => hook.deliveries({ status, limit: 50 }));
    return (
        <Titled title="Recent deliveries" right={<Segmented label="Deliveries" options={DELIVERY_VIEWS} value={view} onChange={setView} />}>
            {deliveries.error !== undefined ? (
                <ErrorPanel error={deliveries.error} onRetry={() => void deliveries.refresh()} />
            ) : deliveries.loading ? (
                <div aria-busy className="h-24 animate-pulse rounded-lg bg-foreground/[0.04]" />
            ) : deliveries.data?.length ? (
                <DeliveryRows rows={deliveries.data} onOpen={onOpen} />
            ) : (
                <p className="m-0 text-[13px] text-muted-foreground">{view === 'failing' ? 'Nothing is failing.' : 'No deliveries in the last 30 days.'}</p>
            )}
        </Titled>
    );
}

function WebhookDrawer({ webhookId, row, onClose, onRotated }: { webhookId: string | null; row?: Webhook; onClose: () => void; onRotated: (secret: string) => void }) {
    const { client, now } = useConsole();
    const [deliveryId, setDeliveryId] = useSearchParam('delivery');
    const fetched = useV1(webhookId && !row ? `webhooks/${webhookId}` : null, () => Webhook.get(webhookId!, { client }));
    const hook = row ?? fetched.data;
    const deliveries = useV1(hook && deliveryId ? `webhooks/${hook.id}/deliveries?all` : null, () => hook!.deliveries({ limit: 50 }));
    const open = deliveryId ? deliveries.data?.find((d) => d.id === deliveryId) : undefined;
    const [editing, setEditing] = useState(false);
    const [busy, setBusy] = useState(false);

    const toggle = async () => {
        if (!hook) return;
        setBusy(true);
        try {
            await hook.update({ enabled: !hook.enabled });
            invalidateV1('webhooks');
            toast(hook.enabled ? 'Endpoint enabled' : 'Endpoint paused');
        } catch (e) {
            toast.error(errorText(e));
        } finally {
            setBusy(false);
        }
    };
    const failure = hook?.lastFailure;

    return (
        <Drawer
            open={webhookId !== null}
            onOpenChange={(o) => {
                if (o) return;
                setDeliveryId(null);
                onClose();
            }}
            kind="webhook"
            id={webhookId ?? undefined}
            title={hook ? <span className="break-all font-mono text-[14px]">{hook.url}</span> : undefined}
            status={hook ? <StatusPill look={webhookLook(hook)} /> : undefined}
            footer={
                hook ? (
                    <>
                        <ConsoleButton disabled={busy} onClick={() => void toggle()}>
                            {hook.enabled ? 'Pause' : 'Enable'}
                        </ConsoleButton>
                        <RotateSecret hook={hook} onRotated={onRotated} />
                        <ConfirmAction
                            label="Delete endpoint"
                            title={`Delete ${hook.url}?`}
                            description="Deliveries stop at once, including the ones still retrying. Events stay in the log for 30 days."
                            confirmLabel="Delete endpoint"
                            onConfirm={async () => {
                                await hook.delete();
                                invalidateV1('webhooks');
                                onClose();
                            }}
                        />
                    </>
                ) : undefined
            }
        >
            {!hook && fetched.error !== undefined && <ErrorPanel error={fetched.error} onRetry={() => void fetched.refresh()} />}
            {!hook && fetched.error === undefined && <div aria-busy className="h-40 animate-pulse rounded-lg bg-foreground/[0.04]" />}
            {hook && deliveryId && (open ? (
                <DeliveryView hook={hook} delivery={open} onBack={() => setDeliveryId(null)} />
            ) : deliveries.error !== undefined ? (
                <ErrorPanel error={deliveries.error} onRetry={() => void deliveries.refresh()} />
            ) : (
                <p className="m-0 text-[13px] text-muted-foreground">{deliveries.loading ? 'Loading…' : "This delivery isn't among the last 50."}</p>
            ))}
            {hook && !deliveryId && (
                <div className="flex flex-col gap-6">
                    <dl className="m-0">
                        <Field label="Endpoint">
                            <span className="inline-flex min-w-0 items-center gap-1 font-mono text-[12px]">
                                <span className="break-all">{hook.url}</span>
                                <CopyButton value={hook.url} label="Copy URL" />
                            </span>
                        </Field>
                        {hook.description && <Field label="Description">{hook.description}</Field>}
                        <Field label="Receives">{hook.userId ? `${hook.userId}'s events only` : "Every event: your account's and every user's"}</Field>
                        <Field label="Last 24 hours">
                            {hook.successRate24h === null ? <span className="text-muted-foreground">No deliveries</span> : `${formatRate(hook.successRate24h)} of attempts delivered`}
                        </Field>
                        <Field label="Last failure">
                            {failure ? (
                                <span>
                                    <span className="tabular-nums">{String(failure.response_status ?? 'No answer')}</span> {typeof failure.error === 'string' && <span className="text-muted-foreground">{failure.error}</span>}
                                    {typeof failure.at === 'string' && <span className="text-muted-foreground"> · {formatRelative(failure.at, now())}</span>}
                                </span>
                            ) : (
                                <span className="text-muted-foreground">None</span>
                            )}
                        </Field>
                        <Field label="Created">
                            <TimeCell value={hook.createdAt} tier="absolute" />
                        </Field>
                    </dl>
                    <Titled
                        title="Events"
                        right={
                            <ConsoleButton size="sm" variant="ghost" onClick={() => setEditing(true)}>
                                Edit events
                            </ConsoleButton>
                        }
                    >
                        <EventPatterns patterns={hook.events} max={20} wrap />
                    </Titled>
                    <SendTest hook={hook} />
                    <Deliveries hook={hook} onOpen={(d) => setDeliveryId(d.id, { push: true })} />
                    {editing && <EditEventsDialog hook={hook} onClose={() => setEditing(false)} />}
                </div>
            )}
        </Drawer>
    );
}

function RotateSecret({ hook, onRotated }: { hook: Webhook; onRotated: (secret: string) => void }) {
    const [open, setOpen] = useState(false);
    const [leaked, setLeaked] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>(undefined);
    const rotate = async () => {
        setBusy(true);
        setError(undefined);
        try {
            const secret = await hook.rotateSecret(leaked ? { graceS: 0 } : {});
            setOpen(false);
            onRotated(secret);
        } catch (e) {
            setError(e);
        } finally {
            setBusy(false);
        }
    };
    return (
        <>
            <ConsoleButton onClick={() => setOpen(true)}>Rotate secret</ConsoleButton>
            <ConsoleDialog
                open={open}
                onOpenChange={setOpen}
                size="sm"
                mark={<RotateCw aria-hidden className="h-5 w-5" />}
                title="Rotate the signing secret?"
                description="For a day, each delivery is signed with both the new secret and the old one, so your receiver keeps verifying while you deploy the new one."
                footer={
                    <>
                        <ConsoleButton variant="ghost" onClick={() => setOpen(false)}>
                            Cancel
                        </ConsoleButton>
                        <ConsoleButton variant="primary" disabled={busy} onClick={() => void rotate()}>
                            {busy ? 'Rotating…' : 'Rotate secret'}
                        </ConsoleButton>
                    </>
                }
            >
                <SwitchRow
                    label="The old secret leaked"
                    description="Stop signing with it at once. Deliveries fail to verify until you deploy the new one."
                    checked={leaked}
                    onCheckedChange={setLeaked}
                />
                {error !== undefined && <ErrorPanel error={error} className="mt-3" />}
            </ConsoleDialog>
        </>
    );
}

/** The one-time secret, and the receiver code that uses it (only the env tab holds it). */
function SecretReveal({ secret, title, onDone }: { secret: string | null; title: string; onDone: () => void }) {
    return (
        <RevealOnceSecret secret={secret} title={title} description="This is the only time you'll see this signing secret. Your receiver verifies each delivery with it." onDone={onDone}>
            {(value) => (
                <div className="flex flex-col gap-2">
                    <CodeSnippet
                        tabs={[
                            { id: 'env', label: 'env', code: `export NOCLICK_WEBHOOK_SECRET=${value}` },
                            { id: 'python', label: 'Python', code: WEBHOOK_VERIFY.python },
                            { id: 'typescript', label: 'TypeScript', code: WEBHOOK_VERIFY.typescript },
                        ]}
                    />
                    <p className="m-0 text-[12px] text-muted-foreground">
                        Only the env tab holds the secret; the receiver code reads <span className="font-mono">$NOCLICK_WEBHOOK_SECRET</span>.
                    </p>
                </div>
            )}
        </RevealOnceSecret>
    );
}

// ── the page ───────────────────────────────────────────────────────────────

function ListenHint() {
    return (
        <div className={cn('mt-4 flex flex-col gap-2 rounded-lg border px-3.5 py-3 text-[13px] sm:flex-row sm:items-center sm:gap-3', HAIRLINE)}>
            <span className="flex shrink-0 items-center gap-2 text-foreground">
                <Terminal className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />
                Testing on your machine?
            </span>
            <span className="inline-flex min-w-0 items-center gap-1 rounded-md bg-foreground/[0.04] px-2 py-1">
                <code className="truncate font-mono text-[12px] text-foreground/85">{LISTEN_COMMAND}</code>
                <CopyButton value={LISTEN_COMMAND} label="Copy command" />
            </span>
            <span className="text-[12px] text-muted-foreground sm:ml-auto">Forwards events to your laptop, signed.</span>
        </div>
    );
}

export default function Webhooks() {
    const { client } = useConsole();
    const href = useConsoleHref();
    const [user, setUser] = useUserParam();
    const [webhookId, setWebhookId] = useSearchParam('webhook');
    const [secret, setSecret] = useState<{ value: string; title: string } | null>(null);
    const place = { user: defaultWriteUser(user) };
    const paged = usePaged(`webhooks?${user}`, (cursor) => Webhook.listPage({ client, userFilter: user, cursor, limit: 50 }), (w) => w.id);
    const failing = paged.rows.filter((w) => w.status === 'failing').length;
    const columns: Column<Webhook>[] = [
        {
            id: 'endpoint',
            header: 'Endpoint',
            cell: (w) => (
                <span className="flex min-w-0 flex-col py-1">
                    <span className="truncate font-mono text-[12px] text-foreground">{w.url}</span>
                    {w.description && <span className="truncate text-[12px] text-muted-foreground">{w.description}</span>}
                </span>
            ),
        },
        { id: 'events', header: 'Events', priority: 2, width: '17rem', cell: (w) => <EventPatterns patterns={w.events} /> },
        {
            id: 'user',
            header: 'User',
            priority: 3,
            width: '7rem',
            cell: (w) => <span className={w.userId ? 'text-foreground/85' : 'text-muted-foreground'}>{w.userId ?? 'All'}</span>,
        },
        { id: 'status', header: 'Status', width: '8.5rem', cell: (w) => <StatusPill look={webhookLook(w)} /> },
        {
            id: 'rate',
            header: 'Last 24h',
            priority: 2,
            align: 'right',
            width: '6rem',
            cell: (w) => <span className="tabular-nums text-foreground/80" title="Attempts your server answered 2xx">{formatRate(w.successRate24h)}</span>,
        },
    ];
    return (
        <>
            <PageHeader crumbs={[{ label: 'Settings', href: href('settings') }]} title="Webhooks" purpose="Endpoints on your server that receive events as they happen: each delivery signed, and retried for 3 days until your server takes it." />
            <PanelToolbar
                user={user}
                setUser={setUser}
                limit={paged.rows.length ? `${plural(paged.rows.length, 'endpoint')}${failing ? `, ${failing} failing` : ''}` : null}
                action={<NewInCode kind="webhook" place={place} />}
            />
            <DataTable
                label="Webhook endpoints"
                columns={columns}
                rows={paged.rows}
                getRowId={(w) => w.id}
                loading={paged.loading}
                error={paged.error}
                onRetry={() => void paged.refresh()}
                onRowClick={(w) => setWebhookId(w.id, { push: true })}
                selectedId={webhookId}
                nextCursor={paged.nextCursor}
                onLoadMore={() => void paged.loadMore()}
                loadingMore={paged.loadingMore}
                empty={<EmptyCode title="No webhook endpoints yet." hint="Add one to hear about finished runs, answers and failures the moment they happen, instead of polling." snippet={NEW_SNIPPETS.webhook(place)} />}
            />
            <ListenHint />
            <WebhookDrawer
                webhookId={webhookId}
                row={paged.rows.find((w) => w.id === webhookId)}
                onClose={() => setWebhookId(null)}
                onRotated={(value) => setSecret({ value, title: 'Secret rotated' })}
            />
            <SecretReveal secret={secret?.value ?? null} title={secret?.title ?? ''} onDone={() => setSecret(null)} />
        </>
    );
}
