// Logs > Events: every event of the last 30 days, filtered by area and user; the lab
// reads the same page from fixtures. The drawer
// (`?event=`) shows the event as it was delivered and where it went, each delivery
// opening in its webhook's drawer under Settings > Webhooks.
import { Link, useNavigate } from 'react-router';
import { ALL_USERS, Event as NoClickEvent, Webhook, type WebhookDelivery } from 'noclick';
import type { Snippet } from '@/screens/console/lib/snippets';
import { userLabel } from '@/screens/console/lib/userFilter';
import { useConsole, useConsoleHref } from '@/screens/console/hooks/useConsole';
import { usePaged } from '@/sdk/usePaged';
import { useSearchParam, useUserParam } from '@/screens/console/hooks/useQueryState';
import { useV1 } from '@/sdk/useV1';
import { ConsoleButton, consoleButtonClass } from '../ui/Button';
import { DataTable, type Column } from '../ui/DataTable';
import { Drawer } from '../ui/Drawer';
import { EmptyCode } from '../ui/EmptyCode';
import { ErrorPanel } from '../ui/ErrorPanel';
import { FacetSelect } from '../ui/FacetSelect';
import { IdChip } from '../ui/IdChip';
import { JsonView } from '../ui/JsonView';
import { TimeCell } from '../ui/TimeCell';
import { UserFacet } from '../ui/UserFacet';
import { Field, Section } from './resources/shared';
import { DeliveryRows, groupEventTypes, useEventTypes } from './Webhooks';

export const EVENTS_EMPTY: Snippet = {
    python: [
        'import noclick',
        '',
        'for event in noclick.Event.list(type="operation.*", user_filter=noclick.ALL_USERS, limit=20):',
        '    print(event.created_at, event.type, event.data["id"])',
    ].join('\n'),
    typescript: [
        'import { ALL_USERS, Event } from "noclick";',
        '',
        'for (const event of await Event.list({ type: "operation.*", userFilter: ALL_USERS, limit: 20 })) {',
        '  console.log(event.createdAt, event.type, event.data.id);',
        '}',
    ].join('\n'),
};

/** What an event is about, in a few words: `deployment` status-page, `domain` acmebooking.com. */
export function describeObject(data: Record<string, unknown>): { kind: string; label: string | null } {
    const kind = typeof data.object === 'string' ? data.object.replace(/_/g, ' ') : 'object';
    const label = ['name', 'project', 'summary', 'subject', 'card', 'message', 'agent', 'kind'].map((k) => data[k]).find((v): v is string => typeof v === 'string' && !!v);
    return { kind, label: label ?? null };
}

function About({ data }: { data: Record<string, unknown> }) {
    const { kind, label } = describeObject(data);
    return (
        <span className="flex min-w-0 items-baseline gap-1.5">
            <span className="shrink-0 text-muted-foreground">{kind}</span>
            {label && <span className="truncate">{label}</span>}
        </span>
    );
}

const COLUMNS: Column<NoClickEvent>[] = [
    { id: 'time', header: 'Time', width: '7rem', cell: (e) => <TimeCell value={e.createdAt} /> },
    { id: 'type', header: 'Type', width: '15rem', cell: (e) => <span className="font-mono text-[12px]">{e.type}</span> },
    { id: 'about', header: 'About', priority: 2, cell: (e) => <About data={e.data} /> },
    {
        id: 'user',
        header: 'User',
        priority: 2,
        width: '8rem',
        cell: (e) => <span className={e.userId ? 'text-foreground/85' : 'text-muted-foreground'}>{userLabel(e.userId)}</span>,
    },
];

function EventDrawer({ eventId, onClose, onFilter }: { eventId: string | null; onClose: () => void; onFilter: (type: string) => void }) {
    const { client } = useConsole();
    const href = useConsoleHref();
    const navigate = useNavigate();
    // The full view carries the deliveries a listing leaves out.
    const event = useV1(eventId ? `events/${eventId}` : null, () => NoClickEvent.get(eventId!, { client }));
    const hooks = useV1('webhooks?all', () => Webhook.list({ client, userFilter: ALL_USERS, limit: 100 }));
    const e = event.data;
    const urlOf = (d: WebhookDelivery) => hooks.data?.find((w) => w.id === d.webhookId)?.url ?? d.webhookId ?? 'A deleted endpoint';
    const payload = e ? Object.fromEntries(Object.entries(e.raw).filter(([k]) => k !== 'deliveries')) : null;
    return (
        <Drawer
            open={eventId !== null}
            onOpenChange={(o) => !o && onClose()}
            kind="event"
            id={eventId ?? undefined}
            title={e ? <span className="font-mono text-[14px]">{e.type}</span> : undefined}
        >
            {event.error !== undefined && !e && <ErrorPanel error={event.error} onRetry={() => void event.refresh()} />}
            {!e && event.error === undefined && <div aria-busy className="h-40 animate-pulse rounded-lg bg-foreground/[0.04]" />}
            {e && (
                <div className="flex flex-col gap-6">
                    <dl className="m-0">
                        <Field label="Time">
                            <TimeCell value={e.createdAt} tier="absolute" />
                        </Field>
                        <Field label="User">{e.userId ? <span>{e.userId}</span> : <span className="text-muted-foreground">Your account</span>}</Field>
                        <Field label="About">
                            <span className="flex min-w-0 flex-wrap items-center gap-x-2">
                                <About data={e.data} />
                                {typeof e.data.id === 'string' && <IdChip id={e.data.id} />}
                            </span>
                        </Field>
                    </dl>
                    <Section title="Deliveries">
                        {e.deliveries.length ? (
                            <DeliveryRows
                                rows={e.deliveries}
                                showEvent={false}
                                hookUrl={urlOf}
                                onOpen={(d) => navigate(href('settings/webhooks', { webhook: d.webhookId, delivery: d.id }))}
                            />
                        ) : (
                            <p className="m-0 text-[13px] text-muted-foreground">
                                No endpoint receives <span className="font-mono">{e.type}</span>.{' '}
                                <Link to={href('settings/webhooks')} className="text-foreground underline underline-offset-2">
                                    Webhooks
                                </Link>
                            </p>
                        )}
                    </Section>
                    <Section title="As delivered">
                        <JsonView value={payload} />
                    </Section>
                    <div>
                        <ConsoleButton size="sm" onClick={() => onFilter(e.type)}>
                            Only {e.type} events
                        </ConsoleButton>
                    </div>
                </div>
            )}
        </Drawer>
    );
}

/** The event log: newest first across every user, narrowed by area (or one type) and user. */
export function EventsView() {
    const { client } = useConsole();
    const href = useConsoleHref();
    const types = useEventTypes();
    const [type, setType] = useSearchParam('type');
    const [user, setUser] = useUserParam();
    const [eventId, setEventId] = useSearchParam('event');
    const paged = usePaged(`events?${type}&${user}`, (cursor) => NoClickEvent.listPage({ client, type: type?.split(',') ?? undefined, userFilter: user, cursor, limit: 50 }), (e) => e.id);
    const areas = groupEventTypes(types.data ?? []).map((g) => ({ value: g.areas.map((a) => `${a}.*`).join(','), label: g.label }));
    const filtered = type !== null || user !== ALL_USERS;
    return (
        <div className="flex min-w-0 flex-col gap-3">
            <div className="flex flex-wrap items-center gap-1">
                <FacetSelect label="Type" value={type} options={areas} onChange={(v) => setType(v)} anyLabel="All events" />
                <UserFacet value={user} onChange={setUser} />
                <span className="ml-auto text-[13px] text-muted-foreground">
                    Kept for 30 days.{' '}
                    <Link to={href('settings/webhooks')} className="text-foreground underline underline-offset-2">
                        Deliver them to your server
                    </Link>
                </span>
            </div>
            <DataTable
                label="Events"
                columns={COLUMNS}
                rows={paged.rows}
                getRowId={(e) => e.id}
                loading={paged.loading}
                error={paged.error}
                onRetry={() => void paged.refresh()}
                onRowClick={(e) => setEventId(e.id, { push: true })}
                selectedId={eventId}
                nextCursor={paged.nextCursor}
                onLoadMore={() => void paged.loadMore()}
                loadingMore={paged.loadingMore}
                empty={
                    filtered ? (
                        <div className="flex flex-col items-center gap-3 py-8">
                            <p className="m-0 text-center text-[13px] text-muted-foreground">No events match these filters.</p>
                            <Link to={href('logs/events')} className={consoleButtonClass('soft', 'sm')}>
                                Clear filters
                            </Link>
                        </div>
                    ) : (
                        <EmptyCode title="No events yet." hint="Events appear as operations finish, people answer and resources change." snippet={EVENTS_EMPTY} />
                    )
                }
            />
            <EventDrawer
                eventId={eventId}
                onClose={() => setEventId(null)}
                onFilter={(next) => {
                    setEventId(null);
                    setType(next);
                }}
            />
        </div>
    );
}
