// Inboxes: email addresses your code or agents receive mail at. The drawer
// (`?inbox=`) lists what arrived, newest first, opens one message in full and
// replies to its sender; Delete retires the address. An inbox shows its name
// and whose mail wakes its agent, and each message the agent turn it woke, or
// why it woke none. In the lab (designed): the email thread's conversation.
import { useEffect, useState } from 'react';
import { Link } from 'react-router';
import { ArrowLeft, Paperclip } from 'lucide-react';
import { toast } from 'sonner';
import {
    fmtBytes,
    HAIRLINE,
    ROW_HOVER,
    clickableRow,
} from '@/ui/primitives';
import { cn } from '@/ui/utils';
import { Inbox, type InboxMessage, type InboxSenders } from 'noclick';
import { INBOXES_EMPTY } from '@/screens/console/lib/snippets';
import { defaultWriteUser, userLabel } from '@/screens/console/lib/userFilter';
import { useAccount, useConsole, useConsoleHref } from '@/screens/console/hooks/useConsole';
import { useChanged } from '@/lib/useChanged';
import { usePaged } from '@/sdk/usePaged';
import { invalidateV1, useV1 } from '@/sdk/useV1';
import { useSearchParam } from '@/screens/console/hooks/useQueryState';
import { recordRecent } from '@/screens/console/hooks/useRecent';
import { Textarea } from '@/ui/textarea';
import { ConsoleButton } from '../../ui/Button';
import { ConsoleDialog } from '../../ui/ConsoleDialog';
import { CopyButton } from '../../ui/CopyButton';
import { DataTable, type Column } from '../../ui/DataTable';
import { Drawer } from '../../ui/Drawer';
import { EmptyCode } from '../../ui/EmptyCode';
import { ErrorPanel } from '../../ui/ErrorPanel';
import { UserField } from '../../ui/UserField';
import { TimeCell } from '../../ui/TimeCell';
import { conversationParam } from '../OperationDrawer';
import { useAgentNames } from '../lookups';
import {
    ConfirmAction,
    errorText,
    Field,
    INPUT,
    LabeledInput,
    PanelToolbar,
    Section,
    type PanelProps,
} from './shared';

/** Whose mail wakes an inbox's agent. */
export const SENDERS_LABEL: Record<InboxSenders, string> = {
    anyone: 'Anyone',
    users: 'Only your users (proven by a DKIM-aligned signature)',
    owner: "Only the inbox's own user or your account's owner",
};

/** What the woken agent did with a message: its turn, or why none ran (its thread is designed). */
function AgentOutcome({ inbox, message }: { inbox: Inbox; message: InboxMessage }) {
    const href = useConsoleHref();
    const { lab } = useConsole();
    const turn = message.agentOperation;
    return (
        <>
            {lab && message.conversation && inbox.agentId && (
                <Field label="Conversation">
                    <Link to={href(`agents/${inbox.agentId}`, { conv: conversationParam(inbox.userId, message.conversation) })} className="font-mono text-[12px] hover:underline">
                        {message.conversation}
                    </Link>
                </Field>
            )}
            {turn && (
                <Field label="Agent turn">
                    <Link to={href('logs', { op: turn.id })} className="hover:underline">
                        Its reply and tool calls
                    </Link>
                </Field>
            )}
            {message.agentError && (
                <Field label="Agent">
                    <span className="text-red-600 dark:text-red-400">{message.agentError}</span>
                </Field>
            )}
        </>
    );
}

function MessageView({
    inbox,
    messageId,
    onBack,
}: {
    inbox: Inbox;
    messageId: string;
    onBack: () => void;
}) {
    const message = useV1(`inboxes/${inbox.id}/messages/${messageId}`, () =>
        inbox.message(messageId)
    );
    const [reply, setReply] = useState('');
    const [sending, setSending] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const m = message.data;
    const send = async () => {
        if (!m || !reply.trim()) return;
        setSending(true);
        setError(null);
        try {
            const sent = await m.reply(reply.trim());
            setReply('');
            toast(
                `Reply ${sent.status ?? 'sent'} to ${m.sender ?? 'the sender'}`
            );
        } catch (e) {
            setError(errorText(e));
        } finally {
            setSending(false);
        }
    };
    return (
        <div className="flex flex-col gap-4">
            <ConsoleButton
                variant="ghost"
                size="sm"
                className="self-start"
                onClick={onBack}
                icon={<ArrowLeft className="h-3.5 w-3.5" />}
            >
                All messages
            </ConsoleButton>
            {message.error !== undefined && (
                <ErrorPanel
                    error={message.error}
                    onRetry={() => void message.refresh()}
                />
            )}
            {!m && message.error === undefined && (
                <div
                    aria-busy
                    className="h-40 animate-pulse rounded-lg bg-foreground/[0.04]"
                />
            )}
            {m && (
                <>
                    <dl className="m-0">
                        <Field label="From">{m.sender ?? 'Unknown'}</Field>
                        <Field label="Subject">
                            {m.subject ?? (
                                <span className="text-muted-foreground">
                                    (no subject)
                                </span>
                            )}
                        </Field>
                        <Field label="Received">
                            <TimeCell value={m.receivedAt} tier="absolute" />
                        </Field>
                        <Field label="Sender verified">
                            {m.raw.authenticated
                                ? 'Yes (DKIM or SPF passed)'
                                : 'No'}
                        </Field>
                        <AgentOutcome inbox={inbox} message={m} />
                    </dl>
                    <pre
                        className={cn(
                            'm-0 whitespace-pre-wrap rounded-lg border bg-foreground/[0.03] px-3 py-2.5 font-sans text-[13px] leading-relaxed',
                            HAIRLINE
                        )}
                    >
                        {m.text || '(empty)'}
                    </pre>
                    {m.attachments.length > 0 && (
                        <Section title="Attachments">
                            <ul className="m-0 flex list-none flex-col gap-2 p-0">
                                {m.attachments.map((a, i) => (
                                    <li
                                        key={`${String(a.name)}-${i}`}
                                        className={cn(
                                            'rounded-lg border px-3 py-2 text-[13px]',
                                            HAIRLINE
                                        )}
                                    >
                                        <span className="flex items-center gap-2">
                                            <Paperclip className="h-3.5 w-3.5 text-muted-foreground" />
                                            <span className="truncate font-medium">
                                                {String(a.name ?? 'attachment')}
                                            </span>
                                            {typeof a.size_bytes ===
                                                'number' && (
                                                <span className="text-[12px] text-muted-foreground">
                                                    {fmtBytes(a.size_bytes)}
                                                </span>
                                            )}
                                        </span>
                                        {typeof a.text === 'string' &&
                                            a.text && (
                                                <p className="m-0 mt-1 line-clamp-3 text-[12px] text-muted-foreground">
                                                    {a.text}
                                                </p>
                                            )}
                                        {typeof a.digest_error === 'string' && (
                                            <p className="m-0 mt-1 text-[12px] text-muted-foreground">
                                                {a.digest_error}
                                            </p>
                                        )}
                                    </li>
                                ))}
                            </ul>
                        </Section>
                    )}
                    <Section title={`Reply to ${m.sender ?? 'the sender'}`}>
                        <Textarea
                            aria-label="Reply"
                            rows={3}
                            value={reply}
                            onChange={(e) => setReply(e.target.value)}
                            placeholder="Goes to the sender only; the thread is kept."
                        />
                        <div className="mt-2 flex items-center gap-2">
                            <ConsoleButton
                                disabled={sending || !reply.trim()}
                                onClick={() => void send()}
                            >
                                {sending ? 'Sending…' : 'Send reply'}
                            </ConsoleButton>
                            {error && (
                                <span className="text-[12px] text-red-600 dark:text-red-400">
                                    {error}
                                </span>
                            )}
                        </div>
                    </Section>
                </>
            )}
        </div>
    );
}

/** The route's default page (the client's `messages` sends no limit). */
const MESSAGE_PAGE = 50;
const PAGES_PER_READ = 10;

export interface MailRead {
    messages: InboxMessage[];
    /** The last page was full: newer mail may follow. */
    more: boolean;
}

/**
 * Mail oldest first from `after`, a bounded number of pages at a time. The route
 * only reads forward, so the newest mail is reached by reading through.
 */
export async function readMailForward(
    inbox: Inbox,
    after?: string
): Promise<MailRead> {
    const messages: InboxMessage[] = [];
    for (let page = 0; page < PAGES_PER_READ; page++) {
        const batch = await inbox.messages({ after });
        messages.push(...batch);
        if (batch.length < MESSAGE_PAGE) return { messages, more: false };
        after = batch[batch.length - 1].id;
    }
    return { messages, more: true };
}

function InboxDrawer({
    inboxId,
    row,
    onClose,
}: {
    inboxId: string | null;
    row?: Inbox;
    onClose: () => void;
}) {
    const { client } = useConsole();
    const agents = useAgentNames();
    const fetched = useV1(inboxId && !row ? `inboxes/${inboxId}` : null, () =>
        Inbox.get(inboxId!, { client })
    );
    const inbox = row ?? fetched.data;
    const messages = useV1(inbox ? `inboxes/${inbox.id}/messages` : null, () =>
        readMailForward(inbox!)
    );
    const [newer, setNewer] = useState<MailRead | null>(null);
    const [loadingNewer, setLoadingNewer] = useState(false);
    const [newerError, setNewerError] = useState<string | null>(null);
    const [open, setOpen] = useState<string | null>(null);
    // Another inbox, or its mail read again, starts with nothing open.
    if (useChanged(inboxId, messages.data)) {
        setOpen(null);
        setNewer(null);
        setNewerError(null);
    }
    const mail = messages.data
        ? [...messages.data.messages, ...(newer?.messages ?? [])]
        : [];
    const more = newer ? newer.more : !!messages.data?.more;
    const loadNewer = async () => {
        if (!inbox || !mail.length) return;
        setLoadingNewer(true);
        setNewerError(null);
        try {
            const read = await readMailForward(inbox, mail[mail.length - 1].id);
            setNewer((prev) => ({
                messages: [...(prev?.messages ?? []), ...read.messages],
                more: read.more,
            }));
        } catch (e) {
            setNewerError(errorText(e));
        } finally {
            setLoadingNewer(false);
        }
    };
    useEffect(() => {
        if (inbox)
            recordRecent({
                type: 'inbox',
                id: inbox.id,
                label: inbox.address,
                path: 'resources/inboxes',
                params: { inbox: inbox.id },
            });
    }, [inbox?.id]); // eslint-disable-line react-hooks/exhaustive-deps
    return (
        <Drawer
            open={inboxId !== null}
            onOpenChange={(o) => !o && onClose()}
            kind="inbox"
            title={
                inbox ? (
                    <span className="font-mono text-[14px]">
                        {inbox.address}
                    </span>
                ) : undefined
            }
            id={inboxId ?? undefined}
            footer={
                inbox ? (
                    <ConfirmAction
                        label="Delete inbox"
                        title={`Delete ${inbox.address}?`}
                        description="The address stops receiving mail at once. It stays reserved for this account for 180 days, so nobody else can take it."
                        confirmLabel="Delete inbox"
                        onConfirm={async () => {
                            await inbox.delete();
                            invalidateV1('inboxes');
                            invalidateV1('account');
                            onClose();
                        }}
                    />
                ) : undefined
            }
        >
            {!inbox && fetched.error !== undefined && (
                <ErrorPanel
                    error={fetched.error}
                    onRetry={() => void fetched.refresh()}
                />
            )}
            {inbox && open && (
                <MessageView
                    inbox={inbox}
                    messageId={open}
                    onBack={() => setOpen(null)}
                />
            )}
            {inbox && !open && (
                <div className="flex flex-col gap-5">
                    <dl className="m-0">
                        <Field label="Address">
                            <span className="inline-flex items-center gap-1 font-mono text-[12px]">
                                {inbox.address}
                                <CopyButton
                                    value={inbox.address}
                                    label="Copy address"
                                />
                            </span>
                        </Field>
                        {inbox.name && (
                            <Field label="Name">
                                <span className="font-mono text-[12px]">{inbox.name}</span>
                            </Field>
                        )}
                        <Field label="Wakes">
                            {inbox.agentId ? (
                                (agents.get(inbox.agentId)?.name ??
                                inbox.agentId)
                            ) : (
                                <span className="text-muted-foreground">
                                    No agent
                                </span>
                            )}
                        </Field>
                        {inbox.agentId && (
                            <Field label="Mail from">
                                {SENDERS_LABEL[inbox.senders ?? 'anyone']}
                            </Field>
                        )}
                        <Field label="User">
                            {userLabel(inbox.userId)}
                        </Field>
                        <Field label="Created">
                            <TimeCell value={inbox.createdAt} tier="absolute" />
                        </Field>
                    </dl>
                    <Section title="Messages">
                        {messages.error !== undefined ? (
                            <ErrorPanel
                                error={messages.error}
                                onRetry={() => void messages.refresh()}
                            />
                        ) : messages.loading ? (
                            <div
                                aria-busy
                                className="h-24 animate-pulse rounded-lg bg-foreground/[0.04]"
                            />
                        ) : mail.length ? (
                            <>
                                {more && (
                                    <div className="mb-2 flex items-center gap-2 text-[12px] text-muted-foreground">
                                        <span>
                                            Newer mail than these{' '}
                                            {mail.length.toLocaleString()} may
                                            have arrived.
                                        </span>
                                        <ConsoleButton
                                            size="sm"
                                            disabled={loadingNewer}
                                            onClick={() => void loadNewer()}
                                        >
                                            {loadingNewer
                                                ? 'Loading…'
                                                : 'Load newer mail'}
                                        </ConsoleButton>
                                        {newerError && (
                                            <span className="text-red-600 dark:text-red-400">
                                                {newerError}
                                            </span>
                                        )}
                                    </div>
                                )}
                                <ul
                                    aria-label="Messages"
                                    className={cn(
                                        'm-0 -mx-3 list-none p-0',
                                        HAIRLINE
                                    )}
                                >
                                    {[...mail]
                                        .reverse()
                                        .map((m: InboxMessage) => (
                                            <li
                                                key={m.id}
                                                className={cn(
                                                    'flex cursor-pointer items-center gap-3 border-b px-3 py-2 text-[13px] last:border-b-0',
                                                    HAIRLINE,
                                                    ROW_HOVER
                                                )}
                                                {...clickableRow(() =>
                                                    setOpen(m.id)
                                                )}
                                            >
                                                <span className="w-40 shrink-0 truncate">
                                                    {m.sender}
                                                </span>
                                                <span className="min-w-0 flex-1 truncate text-muted-foreground">
                                                    {m.subject ??
                                                        '(no subject)'}
                                                </span>
                                                <TimeCell
                                                    value={m.receivedAt}
                                                    className="text-[12px] text-muted-foreground"
                                                />
                                            </li>
                                        ))}
                                </ul>
                            </>
                        ) : (
                            <p className="m-0 text-[13px] text-muted-foreground">
                                No mail yet.
                            </p>
                        )}
                    </Section>
                </div>
            )}
        </Drawer>
    );
}

function CreateInbox({ defaultUser }: { defaultUser: string | null }) {
    const { client } = useConsole();
    const agents = useAgentNames();
    const [open, setOpen] = useState(false);
    const [user, setUser] = useState<string | null>(defaultUser);
    const [localPart, setLocalPart] = useState('');
    const [agent, setAgent] = useState('');
    const [name, setName] = useState('');
    const [senders, setSenders] = useState<InboxSenders>('anyone');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>(undefined);
    const create = async () => {
        setBusy(true);
        setError(undefined);
        try {
            const inbox = await Inbox.create({
                client,
                user,
                localPart: localPart.trim() || undefined,
                agent: agent || undefined,
                name: name.trim() || undefined,
                senders: agent && senders !== 'anyone' ? senders : undefined,
            });
            setOpen(false);
            invalidateV1('inboxes');
            invalidateV1('account');
            toast(`Created ${inbox.address}`);
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
                    setSenders('anyone');
                    setOpen(true);
                }}
            >
                New inbox
            </ConsoleButton>
            <ConsoleDialog
                open={open}
                onOpenChange={setOpen}
                title="New inbox"
                footer={
                    <ConsoleButton
                        variant="primary"
                        disabled={busy}
                        onClick={() => void create()}
                    >
                        {busy ? 'Creating…' : 'Create'}
                    </ConsoleButton>
                }
            >
                <div className="flex flex-col gap-3">
                    <UserField value={user} onChange={setUser} />
                    <LabeledInput label="Name (optional, what your code calls it)" id="inbox-name">
                        <input
                            id="inbox-name"
                            className={cn(INPUT, 'font-mono')}
                            value={name}
                            onChange={(e) => setName(e.target.value)}
                            placeholder="support"
                        />
                    </LabeledInput>
                    <LabeledInput
                        label="Address (before the @, optional)"
                        id="inbox-local-part"
                    >
                        <input
                            id="inbox-local-part"
                            className={cn(INPUT, 'font-mono')}
                            value={localPart}
                            onChange={(e) => setLocalPart(e.target.value)}
                            placeholder="Generated"
                        />
                    </LabeledInput>
                    <LabeledInput
                        label="Wake an agent on each message"
                        id="inbox-agent"
                    >
                        <select
                            id="inbox-agent"
                            className={INPUT}
                            value={agent}
                            onChange={(e) => setAgent(e.target.value)}
                        >
                            <option value="">No agent</option>
                            {[...agents.values()].map((a) => (
                                <option key={a.id} value={a.id}>
                                    {a.name}
                                </option>
                            ))}
                        </select>
                    </LabeledInput>
                    {agent && (
                        <LabeledInput label="Whose mail wakes it" id="inbox-senders">
                            <select id="inbox-senders" className={INPUT} value={senders} onChange={(e) => setSenders(e.target.value as InboxSenders)}>
                                {(Object.keys(SENDERS_LABEL) as InboxSenders[]).map((k) => (
                                    <option key={k} value={k}>
                                        {SENDERS_LABEL[k]}
                                    </option>
                                ))}
                            </select>
                        </LabeledInput>
                    )}
                    {error !== undefined && <ErrorPanel error={error} />}
                </div>
            </ConsoleDialog>
        </>
    );
}

export function InboxesPanel({ user, setUser }: PanelProps) {
    const { client } = useConsole();
    const account = useAccount().data;
    const agents = useAgentNames();
    const [inboxId, setInbox] = useSearchParam('inbox');
    const paged = usePaged(
        `inboxes?${user}`,
        (cursor) =>
            Inbox.listPage({ client, userFilter: user, cursor, limit: 50 }),
        (i) => i.id
    );
    const columns: Column<Inbox>[] = [
        {
            id: 'address',
            header: 'Address',
            cell: (i) => (
                <span className="group/addr inline-flex min-w-0 items-center gap-1">
                    <span className="truncate font-mono text-[12px]">
                        {i.address}
                    </span>
                    {i.name && (
                        <span className="shrink-0 text-[12px] text-muted-foreground">
                            {i.name}
                        </span>
                    )}
                    <CopyButton
                        value={i.address}
                        label="Copy address"
                        className="opacity-100 md:opacity-0 md:group-hover/addr:opacity-100"
                    />
                </span>
            ),
        },
        {
            id: 'agent',
            header: 'Agent',
            priority: 2,
            width: '9rem',
            cell: (i) =>
                i.agentId ? (
                    (agents.get(i.agentId)?.name ?? i.agentId)
                ) : (
                    <span className="text-muted-foreground">—</span>
                ),
        },
        {
            id: 'user',
            header: 'User',
            priority: 2,
            width: '8rem',
            cell: (i) => (
                <span
                    className={
                        i.userId
                            ? 'font-mono text-[12px]'
                            : 'text-muted-foreground'
                    }
                >
                    {userLabel(i.userId)}
                </span>
            ),
        },
        {
            id: 'created',
            header: 'Created',
            width: '6.5rem',
            cell: (i) => <TimeCell value={i.createdAt} />,
        },
    ];
    return (
        <>
            <PanelToolbar
                user={user}
                setUser={setUser}
                limit={
                    account
                        ? `${account.counts.inboxes} of ${account.limits.inboxes_max} inboxes`
                        : null
                }
                action={
                    <CreateInbox defaultUser={defaultWriteUser(user)} />
                }
            />
            <DataTable
                rowMenu="inbox"
                label="Inboxes"
                columns={columns}
                rows={paged.rows}
                getRowId={(i) => i.id}
                loading={paged.loading}
                error={paged.error}
                onRetry={() => void paged.refresh()}
                onRowClick={(i) => setInbox(i.id, { push: true })}
                selectedId={inboxId}
                nextCursor={paged.nextCursor}
                onLoadMore={() => void paged.loadMore()}
                loadingMore={paged.loadingMore}
                empty={
                    <EmptyCode
                        title="No inboxes yet."
                        hint="An inbox is an email address your code or an agent receives mail at."
                        snippet={INBOXES_EMPTY}
                    />
                }
            />
            <InboxDrawer
                inboxId={inboxId}
                row={paged.rows.find((i) => i.id === inboxId)}
                onClose={() => setInbox(null)}
            />
        </>
    );
}
