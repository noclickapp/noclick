// Queues: durable background work, delivered at least once. The drawer (`?queue=`) charts the
// depth over the last day, peeks at the oldest messages without taking them, sends a test
// message, retries or discards dead letters, exports, clears and deletes.
import { useEffect, useState } from 'react';
import { ChevronRight } from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '@/ui/utils';
import { Queue, type QueueMessage } from 'noclick';
import type { Snippet } from '@/screens/console/lib/snippets';
import { defaultWriteUser, userLabel } from '@/screens/console/lib/userFilter';
import { useConsole } from '@/screens/console/hooks/useConsole';
import { usePaged } from '@/sdk/usePaged';
import { useSearchParam } from '@/screens/console/hooks/useQueryState';
import { recordRecent } from '@/screens/console/hooks/useRecent';
import { invalidateV1, useV1 } from '@/sdk/useV1';
import { ConsoleButton } from '../../ui/Button';
import { ConsoleDialog } from '../../ui/ConsoleDialog';
import { DataTable, type Column } from '../../ui/DataTable';
import { Drawer } from '../../ui/Drawer';
import { EmptyCode } from '../../ui/EmptyCode';
import { ErrorPanel } from '../../ui/ErrorPanel';
import { JsonView } from '../../ui/JsonView';
import { StatusPill } from '../../ui/StatusPill';
import { UserField } from '../../ui/UserField';
import { TimeCell } from '../../ui/TimeCell';
import { ConfirmAction, errorText, Field, INPUT, LabeledInput, PanelToolbar, Section, type PanelProps } from './shared';
import { JsonField, jsonPreview, parseJson } from './DictsQueuesShared';
import { QueuesConsumers, QueuesDepthChart, queuesMessageLook } from './QueuesParts';
import { DeleteByName, ExportSection, formatExact } from './StorageShared';

export const QUEUES_EMPTY: Snippet = {
    python: [
        'import noclick',
        '',
        'jobs = noclick.Queue.from_name("invoices", create_if_missing=True)',
        'jobs.put({"invoice": "INV-1042"})',
        'for msg in jobs.iterate(lease_s=60):',
        '    print("Sending", msg.body["invoice"])',
        '    msg.ack()',
    ].join('\n'),
    typescript: [
        'import { Queue } from "noclick";',
        '',
        'const jobs = Queue.fromName("invoices", { createIfMissing: true });',
        'await jobs.put({ invoice: "INV-1042" });',
        'for await (const msg of jobs.iterate({ leaseS: 60 })) {',
        '  console.log("Sending", msg.body);',
        '  await msg.ack();',
        '}',
    ].join('\n'),
};

/** Messages the drawer peeks at, and the day of depth it charts. */
const PEEK = 10;
const HISTORY_HOURS = 24;

const DELAYS = [
    { value: '0', label: 'Now' },
    { value: '60', label: 'In 1 minute' },
    { value: '3600', label: 'In 1 hour' },
] as const;

const TEST_BODY = '{\n  "test": true,\n  "sent_from": "console"\n}';

function MessageRow({ message, maxAttempts, open, onToggle }: { message: QueueMessage; maxAttempts: number; open: boolean; onToggle: () => void }) {
    return (
        <li>
            <button type="button" aria-expanded={open} onClick={onToggle} className="flex w-full items-center gap-3 px-3 py-2 text-left text-[13px] transition-colors hover:bg-foreground/[0.03]">
                <ChevronRight aria-hidden className={cn('h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform', open && 'rotate-90')} />
                <span className="w-[5.5rem] shrink-0">
                    <StatusPill look={queuesMessageLook(message.status)} />
                </span>
                <span className="min-w-0 flex-1 truncate font-mono text-[12px] text-foreground/85">{jsonPreview(message.body)}</span>
                <span className="hidden shrink-0 text-[12px] tabular-nums text-muted-foreground sm:block">{message.attempts ? `try ${message.attempts} of ${maxAttempts}` : 'not tried'}</span>
                <span className="w-16 shrink-0 text-right text-[12px] text-muted-foreground">
                    <TimeCell value={message.enqueuedAt} />
                </span>
            </button>
            {open && (
                <div className="flex flex-col gap-2 px-3 pb-3 pl-9">
                    <JsonView value={message.body} />
                    <p className="m-0 flex flex-wrap gap-x-3 gap-y-0.5 text-[12px] text-muted-foreground">
                        <span>
                            Put <TimeCell value={message.enqueuedAt} />
                        </span>
                        {message.leaseExpiresAt && (
                            <span>
                                Lease ends <TimeCell value={message.leaseExpiresAt} />
                            </span>
                        )}
                        {message.visibleAt && (
                            <span>
                                Can be taken <TimeCell value={message.visibleAt} />
                            </span>
                        )}
                    </p>
                    {message.lastError && <p className="m-0 text-[12px] text-red-600 dark:text-red-400">Last try: {message.lastError}</p>}
                </div>
            )}
        </li>
    );
}

function SendTestDialog({ queue, open, onOpenChange }: { queue: Queue; open: boolean; onOpenChange: (open: boolean) => void }) {
    const [text, setText] = useState(TEST_BODY);
    const [delay, setDelay] = useState('0');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>(undefined);
    const parsed = parseJson(text);
    const agents = queue.usedBy.filter((u) => u.kind === 'agent').map((u) => u.name);
    const send = async () => {
        if (!parsed.ok) return;
        setBusy(true);
        setError(undefined);
        try {
            await queue.put(parsed.value, { delayS: Number(delay) || undefined });
            onOpenChange(false);
            invalidateV1(`queues`);
            toast(`Sent a test message to ${queue.name}`, {
                description: agents.length ? `${agents.join(' and ')} takes it as a turn${delay === '0' ? '' : ' once it can be taken'}.` : 'The next worker to call get or iterate takes it.',
            });
        } catch (e) {
            setError(e);
        } finally {
            setBusy(false);
        }
    };
    return (
        <ConsoleDialog
            open={open}
            onOpenChange={onOpenChange}
            title={`Send a test message to ${queue.name}`}
            description={
                agents.length
                    ? `A real message: ${agents.join(' and ')} takes it as a turn, billed like any other. Use a body your consumers can tell apart.`
                    : 'A real message: whatever consumes this queue takes it next. Use a body your workers can tell apart.'
            }
            footer={
                <ConsoleButton variant="primary" disabled={busy || !parsed.ok} onClick={() => void send()}>
                    {busy ? 'Sending…' : 'Send'}
                </ConsoleButton>
            }
        >
            <div className="flex flex-col gap-3">
                <JsonField id="queue-test-body" label="Body (JSON)" value={text} onChange={setText} rows={5} hint="Up to 256 KB of JSON." />
                <LabeledInput label="Deliver" id="queue-test-delay">
                    <select id="queue-test-delay" className={INPUT} value={delay} onChange={(e) => setDelay(e.target.value)}>
                        {DELAYS.map((d) => (
                            <option key={d.value} value={d.value}>
                                {d.label}
                            </option>
                        ))}
                    </select>
                </LabeledInput>
                {error !== undefined && <ErrorPanel error={error} />}
            </div>
        </ConsoleDialog>
    );
}

function MessagesSection({ queue }: { queue: Queue }) {
    const peek = useV1(`queues/${queue.id}/peek`, () => queue.peek({ limit: PEEK }));
    const [open, setOpen] = useState<string | null>(null);
    const [sending, setSending] = useState(false);
    const total = queue.depth + queue.inFlight;
    return (
        <section>
            <div className="mb-2 flex items-center justify-between gap-2">
                <h3 className="m-0 text-[14px] font-semibold tracking-[-0.01em] text-foreground">Messages</h3>
                <ConsoleButton size="sm" onClick={() => setSending(true)}>
                    Send a test message
                </ConsoleButton>
            </div>
            {peek.error !== undefined && !peek.data ? (
                <ErrorPanel error={peek.error} onRetry={() => void peek.refresh()} />
            ) : !peek.data ? (
                <div aria-busy className="h-32 animate-pulse rounded-lg bg-foreground/[0.04]" />
            ) : peek.data.length ? (
                <>
                    <p className="m-0 mb-2 text-[12px] text-muted-foreground">
                        {peek.data.length < total ? `The oldest ${peek.data.length} of ${formatExact(total)}` : 'All of them'}, waiting and in flight. Looking takes nothing off the queue.
                    </p>
                    <ul aria-label="Messages" className={'m-0 -mx-3 list-none p-0'}>
                        {peek.data.map((m) => (
                            <MessageRow key={m.id} message={m} maxAttempts={queue.maxAttempts} open={open === m.id} onToggle={() => setOpen(open === m.id ? null : m.id)} />
                        ))}
                    </ul>
                </>
            ) : (
                <p className="m-0 text-[13px] text-muted-foreground">Nothing waiting. Your code puts work on with queue.put, or send a test message.</p>
            )}
            {sending && <SendTestDialog queue={queue} open={sending} onOpenChange={setSending} />}
        </section>
    );
}

function DeadLetterRow({ letter, onDone }: { letter: QueueMessage; onDone: (id: string, verb: 'retried' | 'discarded') => void }) {
    const [busy, setBusy] = useState(false);
    const [asking, setAsking] = useState(false);
    const [error, setError] = useState<unknown>(undefined);
    const run = async (verb: 'retried' | 'discarded') => {
        setBusy(true);
        setError(undefined);
        try {
            await (verb === 'retried' ? letter.retry() : letter.discard());
            setAsking(false);
            onDone(letter.id, verb);
        } catch (e) {
            if (verb === 'retried') toast.error(errorText(e));
            else setError(e);
        } finally {
            setBusy(false);
        }
    };
    return (
        <li className="flex flex-col gap-2 px-3 py-2.5 sm:flex-row sm:items-start">
            <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                <span className="truncate font-mono text-[12px] text-foreground/85">{jsonPreview(letter.body)}</span>
                {letter.lastError && <span className="text-[13px] text-red-600 dark:text-red-400">{letter.lastError}</span>}
                <span className="text-[12px] text-muted-foreground">
                    {letter.attempts} tries · dead <TimeCell value={letter.deadLetteredAt} />
                </span>
            </div>
            <div className="flex shrink-0 items-center gap-1.5">
                <ConsoleButton size="sm" disabled={busy} onClick={() => void run('retried')}>
                    Retry
                </ConsoleButton>
                <ConsoleButton variant="ghost" size="sm" disabled={busy} onClick={() => setAsking(true)}>
                    Discard
                </ConsoleButton>
            </div>
            <ConsoleDialog
                open={asking}
                onOpenChange={setAsking}
                size="sm"
                title="Discard this dead letter?"
                description="It's deleted for good and never delivered again. Retry puts it back on the queue instead."
                footer={
                    <>
                        <ConsoleButton variant="ghost" onClick={() => setAsking(false)}>
                            Cancel
                        </ConsoleButton>
                        <ConsoleButton variant="danger" disabled={busy} onClick={() => void run('discarded')}>
                            {busy ? 'Discarding…' : 'Discard'}
                        </ConsoleButton>
                    </>
                }
            >
                <div className="flex flex-col gap-2">
                    <JsonView value={letter.body} />
                    {error !== undefined && <ErrorPanel error={error} />}
                </div>
            </ConsoleDialog>
        </li>
    );
}

function DeadLettersSection({ queue }: { queue: Queue }) {
    const letters = useV1(`queues/${queue.id}/dead_letters`, () => queue.deadLetters({ limit: 50 }));
    const [gone, setGone] = useState<Set<string>>(new Set());
    const rows = (letters.data ?? []).filter((l) => !gone.has(l.id));
    return (
        <Section title="Dead letters">
            {letters.error !== undefined && !letters.data ? (
                <ErrorPanel error={letters.error} onRetry={() => void letters.refresh()} />
            ) : !letters.data ? (
                <div aria-busy className="h-16 animate-pulse rounded-lg bg-foreground/[0.04]" />
            ) : rows.length ? (
                <ul aria-label="Dead letters" className={'m-0 -mx-3 list-none p-0'}>
                    {rows.map((l) => (
                        <DeadLetterRow
                            key={l.id}
                            letter={l}
                            onDone={(id, verb) => {
                                setGone((prev) => new Set(prev).add(id));
                                invalidateV1('queues');
                                toast(verb === 'retried' ? `Back on ${queue.name}, with its tries reset` : 'Discarded the dead letter');
                            }}
                        />
                    ))}
                </ul>
            ) : (
                <p className="m-0 text-[13px] text-muted-foreground">None. A message lands here after failing {queue.maxAttempts} times, with why.</p>
            )}
        </Section>
    );
}

function DepthSection({ queue }: { queue: Queue }) {
    const history = useV1(`queues/${queue.id}/depth`, () => queue.depthHistory({ hours: HISTORY_HOURS }));
    return (
        <Section title="Depth, last 24 hours">
            {history.error !== undefined && !history.data ? (
                <ErrorPanel error={history.error} onRetry={() => void history.refresh()} />
            ) : !history.data ? (
                <div aria-busy className="h-24 animate-pulse rounded-lg bg-foreground/[0.04]" />
            ) : (
                <QueuesDepthChart points={history.data} hours={HISTORY_HOURS} />
            )}
        </Section>
    );
}

function QueueDrawer({ queueId, row, onClose }: { queueId: string | null; row?: Queue; onClose: () => void }) {
    const { client } = useConsole();
    const fetched = useV1(queueId && !row ? `queues/${queueId}` : null, () => Queue.fromId(queueId!, { client }).hydrate());
    const queue = row ?? fetched.data;
    useEffect(() => {
        if (queue) recordRecent({ type: 'queue', id: queue.id, label: queue.name, path: 'resources/queues', params: { queue: queue.id } });
    }, [queue?.id]); // eslint-disable-line react-hooks/exhaustive-deps
    const agent = queue?.usedBy.find((u) => u.kind === 'agent');
    const app = queue?.usedBy.find((u) => u.kind !== 'agent');
    return (
        <Drawer
            open={queueId !== null}
            onOpenChange={(o) => !o && onClose()}
            kind="queue"
            title={queue?.name}
            id={queueId ?? undefined}
            footer={
                queue ? (
                    <DeleteByName
                        label="Delete queue"
                        name={queue.name}
                        description={
                            agent
                                ? `${agent.name}'s OnQueue trigger reads it, so the delete is refused until you remove the trigger.`
                                : app
                                  ? `${app.name} binds it, so the delete is refused until you unbind it.`
                                  : `Its ${formatExact(queue.depth)} waiting messages and ${formatExact(queue.deadLetterCount)} dead letters are deleted with it.`
                        }
                        onConfirm={async () => {
                            await queue.delete();
                            invalidateV1('queues');
                            invalidateV1('account');
                            toast(`Deleted ${queue.name}`);
                            onClose();
                        }}
                    />
                ) : undefined
            }
        >
            {!queue && fetched.error !== undefined && <ErrorPanel error={fetched.error} onRetry={() => void fetched.refresh()} />}
            {!queue && fetched.error === undefined && <div aria-busy className="h-40 animate-pulse rounded-lg bg-foreground/[0.04]" />}
            {queue && (
                <div key={queue.id} className="flex flex-col gap-6">
                    <dl className="m-0">
                        <Field label="Waiting">
                            <span className="tabular-nums">{formatExact(queue.depth)}</span>
                        </Field>
                        <Field label="In flight">
                            <span className="tabular-nums">{formatExact(queue.inFlight)}</span>
                        </Field>
                        <Field label="Dead letters">
                            <span className={cn('tabular-nums', queue.deadLetterCount > 0 && 'text-red-600 dark:text-red-400')}>{formatExact(queue.deadLetterCount)}</span>
                        </Field>
                        <Field label="Tries">
                            Up to {queue.maxAttempts} per message <span className="text-muted-foreground">(max_attempts)</span>
                        </Field>
                        <Field label="Consumers">
                            <QueuesConsumers users={queue.usedBy} links />
                        </Field>
                        <Field label="User">{userLabel(queue.userId)}</Field>
                        <Field label="Created">
                            <TimeCell value={queue.createdAt} tier="absolute" />
                        </Field>
                    </dl>
                    <DepthSection queue={queue} />
                    <MessagesSection queue={queue} />
                    <DeadLettersSection queue={queue} />
                    <Section title="Clear">
                        <div className="flex flex-wrap items-center gap-3">
                            <p className="m-0 min-w-0 flex-1 text-[13px] text-muted-foreground">Drop every waiting message and dead letter. Messages in flight finish as usual.</p>
                            <ConfirmAction
                                label="Clear queue"
                                title={`Clear ${queue.name}?`}
                                description={`${formatExact(queue.depth)} waiting messages and ${formatExact(queue.deadLetterCount)} dead letters are dropped now and never delivered. The ${formatExact(queue.inFlight)} in flight finish as usual.`}
                                confirmLabel="Clear queue"
                                onConfirm={async () => {
                                    await queue.clear();
                                    invalidateV1('queues');
                                    toast(`Cleared ${queue.name}`);
                                }}
                            />
                        </div>
                    </Section>
                    <ExportSection what="JSON Lines: every message, dead letters too, one per line with its status." start={() => queue.export()} />
                </div>
            )}
        </Drawer>
    );
}

function CreateQueue({ defaultUser }: { defaultUser: string | null }) {
    const { client } = useConsole();
    const [open, setOpen] = useState(false);
    const [user, setUser] = useState<string | null>(defaultUser);
    const [name, setName] = useState('');
    const [attempts, setAttempts] = useState('5');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>(undefined);
    const tries = Number(attempts);
    const triesOk = Number.isInteger(tries) && tries >= 1 && tries <= 100;
    const create = async () => {
        setBusy(true);
        setError(undefined);
        try {
            const queue = await Queue.create(name.trim(), { client, user, maxAttempts: tries });
            setOpen(false);
            invalidateV1('queues');
            invalidateV1('account');
            toast(`Created ${queue.name}`);
        } catch (e) {
            setError(e);
        } finally {
            setBusy(false);
        }
    };
    return (
        <>
            <ConsoleButton
                variant="primary"
                onClick={() => {
                    setUser(defaultUser);
                    setName('');
                    setAttempts('5');
                    setError(undefined);
                    setOpen(true);
                }}
            >
                New queue
            </ConsoleButton>
            <ConsoleDialog
                open={open}
                onOpenChange={setOpen}
                title="New queue"
                description="Your code reaches it by name, as its user: Queue.from_name."
                footer={
                    <ConsoleButton variant="primary" disabled={busy || !name.trim() || !triesOk} onClick={() => void create()}>
                        {busy ? 'Creating…' : 'Create'}
                    </ConsoleButton>
                }
            >
                <div className="flex flex-col gap-3">
                    <LabeledInput label="Name" id="queue-name">
                        <input id="queue-name" className={cn(INPUT, 'font-mono')} value={name} onChange={(e) => setName(e.target.value)} placeholder="invoices" autoComplete="off" />
                    </LabeledInput>
                    <div className="flex flex-col gap-1.5">
                        <LabeledInput label="Tries per message" id="queue-attempts">
                            <input id="queue-attempts" type="number" min={1} max={100} className={cn(INPUT, 'w-28 tabular-nums')} value={attempts} onChange={(e) => setAttempts(e.target.value)} />
                        </LabeledInput>
                        <span className={cn('text-[12px]', triesOk ? 'text-muted-foreground' : 'text-red-600 dark:text-red-400')}>
                            {triesOk ? 'After this many failed deliveries a message becomes a dead letter.' : 'A whole number from 1 to 100.'}
                        </span>
                    </div>
                    <UserField value={user} onChange={setUser} />
                    {error !== undefined && <ErrorPanel error={error} />}
                </div>
            </ConsoleDialog>
        </>
    );
}

export function QueuesPanel({ user, setUser }: PanelProps) {
    const { client } = useConsole();
    const [queueId, setQueue] = useSearchParam('queue');
    const paged = usePaged(`queues?${user}`, (cursor) => Queue.listPage({ client, userFilter: user, cursor, limit: 50 }), (q) => q.id);
    const columns: Column<Queue>[] = [
        { id: 'name', header: 'Name', cell: (q) => <span className="truncate font-medium text-foreground">{q.name}</span> },
        { id: 'waiting', header: 'Waiting', width: '5.5rem', align: 'right', cell: (q) => <span className="tabular-nums">{formatExact(q.depth)}</span> },
        { id: 'flight', header: 'In flight', width: '5.5rem', align: 'right', priority: 2, cell: (q) => <span className="tabular-nums">{formatExact(q.inFlight)}</span> },
        {
            id: 'dead',
            header: 'Dead letters',
            width: '6.5rem',
            align: 'right',
            cell: (q) => <span className={cn('tabular-nums', q.deadLetterCount > 0 ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground')}>{formatExact(q.deadLetterCount)}</span>,
        },
        { id: 'consumers', header: 'Used by', priority: 3, cell: (q) => <QueuesConsumers users={q.usedBy} /> },
        {
            id: 'user',
            header: 'User',
            width: '8rem',
            priority: 2,
            cell: (q) => <span className={q.userId ? 'text-foreground/85' : 'text-muted-foreground'}>{userLabel(q.userId)}</span>,
        },
    ];
    return (
        <>
            <PanelToolbar user={user} setUser={setUser} action={<CreateQueue defaultUser={defaultWriteUser(user)} />} />
            <DataTable
                rowMenu="queue"
                label="Queues"
                columns={columns}
                rows={paged.rows}
                getRowId={(q) => q.id}
                loading={paged.loading}
                error={paged.error}
                onRetry={() => void paged.refresh()}
                onRowClick={(q) => setQueue(q.id, { push: true })}
                selectedId={queueId}
                nextCursor={paged.nextCursor}
                onLoadMore={() => void paged.loadMore()}
                loadingMore={paged.loadingMore}
                empty={<EmptyCode title="No queues yet." hint="Work handed from your app to a worker or an agent, retried until it's done." snippet={QUEUES_EMPTY} />}
            />
            <QueueDrawer queueId={queueId} row={paged.rows.find((q) => q.id === queueId)} onClose={() => setQueue(null)} />
        </>
    );
}
