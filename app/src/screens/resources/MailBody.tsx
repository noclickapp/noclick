// An email address's page body: its threads, the most recently active first,
// and one thread whole (?thread=): what arrived and what was sent from the
// address, oldest first, with a reply to the person it's with under it. An
// address on a domain the account bought also writes new mail (?compose=1),
// one person at a time, and follows up on a thread once a reply can't be sent.
import { useState, type FormEvent } from 'react';
import { useSearchParams } from 'react-router';
import { toast } from 'sonner';
import { ArrowLeft, Loader2, Paperclip } from 'lucide-react';
import { fmtBytes, relTime } from '@/ui/primitives';
import { BUTTON_PRIMARY, BUTTON_SECONDARY } from '@/ui/buttons';
import { FIELD, FIELD_LABEL } from '@/ui/fields';
import { usePlatformResources } from './platform';
import { Section, Surface } from './ui';
import { cn } from '@/ui/utils';
import { errorText } from '@/screens/console/pages/resources/shared';
import { invalidateV1, useV1 } from '@/sdk/useV1';
import type { Inbox, InboxMessage, InboxThread } from 'noclick';
import { Pending, ROW } from './parts';

/** How long after a message arrives a reply to it can be sent (the platform's reply window). */
const REPLY_WINDOW_MS = 48 * 60 * 60 * 1000;

/** Whether an address writes new mail: one at a domain whose DNS NoClick runs (one the account bought), or under one. */
export function writesNewMail(address: string, mailDomains: readonly string[]): boolean {
    const domain = address.slice(address.lastIndexOf('@') + 1).toLowerCase();
    return mailDomains.some((d) => domain === d || domain.endsWith(`.${d}`));
}

/** What became of mail the address sent, when it's worth saying: still going, or not landed. */
function sentNote(message: InboxMessage): { text: string; failed: boolean } | null {
    if (message.status === 'sending') return { text: 'Sending', failed: false };
    if (message.status === 'failed') return { text: `Not sent${message.deliveryError ? `: ${message.deliveryError}` : ''}`, failed: true };
    if (message.deliveryStatus === 'bounced') return { text: message.deliveryError ?? 'Bounced', failed: true };
    if (message.deliveryStatus === 'complained') return { text: 'Marked as spam by the recipient', failed: true };
    return null;
}

/** "Ada Lovelace <ada@example.com>" → "Ada Lovelace"; a bare address stays itself. */
export function personName(address: string | null): string {
    if (!address) return 'Unknown sender';
    const named = /^\s*"?([^"<]+?)"?\s*<[^>]+>\s*$/.exec(address);
    return named ? named[1] : address;
}

/** The address part of "Name <address>". */
function bareAddress(address: string | null): string | null {
    return address ? (/<([^>]+)>/.exec(address)?.[1] ?? address) : null;
}

const threadsKey = (inbox: Inbox) => `resources:inbox:${inbox.id}:threads`;

export function MailBody({ inbox, now }: { inbox: Inbox; now: string }) {
    const [params, setParams] = useSearchParams();
    const writes = writesNewMail(inbox.address, usePlatformResources()?.mailDomains ?? []);
    const threadId = params.get('thread');
    const show = (view: { thread?: string; compose?: boolean } | null) =>
        setParams(
            (prev) => {
                const next = new URLSearchParams(prev);
                next.delete('thread');
                next.delete('compose');
                if (view?.thread) next.set('thread', view.thread);
                if (view?.compose) next.set('compose', '1');
                return next;
            },
            { replace: !view }
        );
    if (threadId) return <Thread inbox={inbox} threadId={threadId} now={now} writes={writes} onBack={() => show(null)} />;
    if (writes && params.get('compose') === '1') return <Compose inbox={inbox} onBack={() => show(null)} />;
    return <Threads inbox={inbox} now={now} onOpen={(id) => show({ thread: id })} onCompose={writes ? () => show({ compose: true }) : undefined} />;
}

function Threads({ inbox, now, onOpen, onCompose }: { inbox: Inbox; now: string; onOpen: (id: string) => void; onCompose?: () => void }) {
    const read = useV1(threadsKey(inbox), () => inbox.threads({ limit: 50 }));
    const threads = read.data?.data;
    return (
        <Section
            title="Mail"
            meta={threads?.length ? threads.length : undefined}
            action={
                onCompose && (
                    <button type="button" className={BUTTON_SECONDARY} onClick={onCompose}>
                        New email
                    </button>
                )
            }
        >
            <Pending read={read} />
            {threads &&
                (threads.length ? (
                    <Surface>
                        {threads.map((t) => (
                            <ThreadRow key={t.id} thread={t} now={now} onOpen={() => onOpen(t.id)} />
                        ))}
                    </Surface>
                ) : (
                    <p className="text-[14px] leading-relaxed text-muted-foreground">
                        No mail yet. Mail sent to {inbox.address}
                        {onCompose ? ', and mail you write from it, shows up here.' : ' shows up here.'}
                    </p>
                ))}
        </Section>
    );
}

function ThreadRow({ thread, now, onOpen }: { thread: InboxThread; now: string; onOpen: () => void }) {
    const snippet = thread.snippet ? `${thread.lastDirection === 'outbound' ? 'You: ' : ''}${thread.snippet}` : null;
    return (
        <button type="button" onClick={onOpen} className={cn(ROW, 'w-full items-start text-left transition-colors hover:bg-foreground/[0.03] focus-visible:bg-foreground/[0.04] focus-visible:outline-none')}>
            <span className="min-w-0 flex-1">
                <span className="flex items-baseline gap-2">
                    <span className="truncate text-[14px] font-medium text-foreground">{personName(thread.correspondent)}</span>
                    {thread.messageCount > 1 && <span className="shrink-0 text-[12px] tabular-nums text-muted-foreground">{thread.messageCount}</span>}
                </span>
                <span className="block truncate text-[13.5px] text-foreground/85">{thread.subject || '(no subject)'}</span>
                {snippet && <span className="block truncate text-[13px] text-muted-foreground">{snippet}</span>}
            </span>
            <span className="shrink-0 pt-0.5 text-[12.5px] tabular-nums text-muted-foreground">{thread.lastAt ? relTime(thread.lastAt.toISOString(), now) : ''}</span>
        </button>
    );
}

function BackToMail({ onBack }: { onBack: () => void }) {
    return (
        <button type="button" onClick={onBack} className="mb-3 inline-flex items-center gap-1.5 rounded-md text-[13px] text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
            <ArrowLeft className="h-3.5 w-3.5" />
            All mail
        </button>
    );
}

function Thread({ inbox, threadId, now, writes, onBack }: { inbox: Inbox; threadId: string; now: string; writes: boolean; onBack: () => void }) {
    const read = useV1(`resources:inbox:${inbox.id}:thread:${threadId}`, () => inbox.thread(threadId));
    const thread = read.data;
    // A reply answers the newest message that arrived on the thread, while it still can; after that (or with
    // nothing received yet) an address that writes new mail follows up on the thread instead.
    const received = thread?.messages.filter((m) => m.direction === 'inbound') ?? [];
    const answering = received[received.length - 1];
    const replies = answering?.receivedAt && Date.parse(now) - answering.receivedAt.getTime() < REPLY_WINDOW_MS;
    const sent = () => invalidateV1(`resources:inbox:${inbox.id}`);
    // Nobody to write to once mail to them bounced or was marked as spam: the platform won't mail them again.
    const lost = thread?.messages.some((m) => m.direction === 'outbound' && (m.deliveryStatus === 'bounced' || m.deliveryStatus === 'complained'));
    const correspondent = lost ? null : (thread?.correspondent ?? null);
    return (
        <section className="mt-10">
            <BackToMail onBack={onBack} />
            <Pending read={read} rows={2} />
            {thread && (
                <>
                    <h2 className="mb-3 break-words text-[17px] font-semibold tracking-[-0.01em] text-foreground">{thread.subject || '(no subject)'}</h2>
                    <Surface>
                        {thread.messages.map((m) => (
                            <Message key={m.id} message={m} now={now} />
                        ))}
                    </Surface>
                    {answering && replies ? (
                        <Composer
                            label={`Reply to ${personName(answering.sender)}`}
                            note={`Goes to ${bareAddress(answering.sender)} only, from ${inbox.address}, on this thread.`}
                            action="Send reply"
                            send={async (text) => {
                                await answering.reply(text);
                                toast.success(`Reply sent to ${bareAddress(answering.sender)}`);
                                sent();
                            }}
                        />
                    ) : (
                        writes &&
                        correspondent && (
                            <Composer
                                label={`Write to ${personName(correspondent)}`}
                                note={`Goes to ${bareAddress(correspondent)} from ${inbox.address}, on this thread.`}
                                action="Send"
                                send={async (text) => {
                                    const message = await inbox.send({ text, thread: threadId });
                                    toast.success(message.status === 'sending' ? `Sending to ${bareAddress(correspondent)}` : `Sent to ${bareAddress(correspondent)}`);
                                    sent();
                                }}
                            />
                        )
                    )}
                </>
            )}
        </section>
    );
}

function Message({ message, now }: { message: InboxMessage; now: string }) {
    const sent = message.direction === 'outbound';
    const who = sent ? 'You' : personName(message.sender);
    // Beside the name, the address it's from (or to): only where the name isn't already the address.
    const address = sent ? `to ${bareAddress(String(message.to ?? ''))}` : bareAddress(message.sender);
    const note = sent ? sentNote(message) : null;
    return (
        <article className={cn('border-b border-border px-4 py-4 last:border-0 dark:border-foreground/[0.06]', sent && 'bg-foreground/[0.025]')} data-testid={sent ? 'sent-message' : 'received-message'}>
            <header className="mb-2 flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                <span className="text-[14px] font-medium text-foreground">{who}</span>
                {address !== who && <span className="min-w-0 truncate text-[12.5px] text-muted-foreground">{address}</span>}
                <span className="ml-auto text-[12.5px] tabular-nums text-muted-foreground">{message.receivedAt ? relTime(message.receivedAt.toISOString(), now) : ''}</span>
            </header>
            {note && <p className={cn('mb-2 text-[12.5px]', note.failed ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground')}>{note.text}</p>}
            <p className="whitespace-pre-wrap break-words text-[14px] leading-relaxed text-foreground/90">{message.text || '(no text)'}</p>
            {message.attachments.length > 0 && (
                <ul className="mt-3 flex flex-wrap gap-2">
                    {message.attachments.map((a, i) => {
                        const name = String(a.name ?? 'attachment');
                        const size = typeof a.size_bytes === 'number' ? fmtBytes(a.size_bytes) : null;
                        const label = (
                            <>
                                <Paperclip className="h-3.5 w-3.5 shrink-0" />
                                <span className="truncate">{name}</span>
                                {size && <span className="shrink-0 text-muted-foreground">{size}</span>}
                            </>
                        );
                        const chip = 'inline-flex max-w-full items-center gap-1.5 rounded-full bg-foreground/[0.05] px-3 py-1 text-[12.5px] text-foreground';
                        return (
                            <li key={i} className="min-w-0">
                                {typeof a.url === 'string' ? (
                                    <a href={a.url} target="_blank" rel="noopener noreferrer" className={cn(chip, 'hover:bg-foreground/[0.08]')}>
                                        {label}
                                    </a>
                                ) : (
                                    <span className={chip}>{label}</span>
                                )}
                            </li>
                        );
                    })}
                </ul>
            )}
        </article>
    );
}

const TEXTAREA = cn(FIELD, 'h-auto min-h-[132px] resize-y py-2.5 leading-relaxed');

/** Runs ``send`` once the form is filled, holding it while it goes and saying why one didn't. */
function useSending(send: () => Promise<void>) {
    const [sending, setSending] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const submit = async (event: FormEvent) => {
        event.preventDefault();
        if (sending) return;
        setSending(true);
        setError(null);
        try {
            await send();
        } catch (err) {
            setError(errorText(err));
        } finally {
            setSending(false);
        }
    };
    return { sending, error, submit };
}

function Failure({ error }: { error: string | null }) {
    return error ? (
        <p role="alert" className="mt-3 text-[13.5px] text-red-600 dark:text-red-400">
            {error}
        </p>
    ) : null;
}

/** A message on the thread, under it: a reply to its latest arrival, or more mail to the person it's with. */
function Composer({ label, note, action, send }: { label: string; note: string; action: string; send: (text: string) => Promise<void> }) {
    const [text, setText] = useState('');
    const { sending, error, submit } = useSending(async () => {
        await send(text.trim());
        setText('');
    });
    return (
        <form onSubmit={(e) => void submit(e)} className="mt-8">
            <label htmlFor="mail-reply" className={FIELD_LABEL}>
                {label}
            </label>
            <textarea id="mail-reply" value={text} onChange={(e) => setText(e.target.value)} rows={5} disabled={sending} placeholder="Write your message" className={TEXTAREA} />
            <p className="mt-2 text-[13px] text-muted-foreground">{note}</p>
            <Failure error={error} />
            <button type="submit" disabled={!text.trim() || sending} className={cn(BUTTON_PRIMARY, 'mt-4')}>
                {sending && <Loader2 className="h-4 w-4 animate-spin" />}
                {action}
            </button>
        </form>
    );
}

/** New mail from the address to one person; it then waits among the address's threads. */
function Compose({ inbox, onBack }: { inbox: Inbox; onBack: () => void }) {
    const [to, setTo] = useState('');
    const [subject, setSubject] = useState('');
    const [text, setText] = useState('');
    const ready = Boolean(to.trim() && subject.trim() && text.trim());
    const { sending, error, submit } = useSending(async () => {
        const message = await inbox.send({ to: to.trim(), subject: subject.trim(), text: text.trim() });
        // The first time an address sends, NoClick sets up its sending: the message goes a few minutes later.
        toast.success(message.status === 'sending' ? `Sending to ${to.trim()}: it goes out within a few minutes` : `Sent to ${to.trim()}`);
        invalidateV1(`resources:inbox:${inbox.id}`);
        onBack();
    });
    return (
        <section className="mt-10">
            <BackToMail onBack={onBack} />
            <h2 className="mb-5 text-[17px] font-semibold tracking-[-0.01em] text-foreground">New email</h2>
            <form onSubmit={(e) => void submit(e)} className="space-y-5">
                <div>
                    <label htmlFor="mail-to" className={FIELD_LABEL}>
                        To
                    </label>
                    <input id="mail-to" type="email" value={to} onChange={(e) => setTo(e.target.value)} disabled={sending} placeholder="name@example.com" autoComplete="off" className={FIELD} />
                </div>
                <div>
                    <label htmlFor="mail-subject" className={FIELD_LABEL}>
                        Subject
                    </label>
                    <input id="mail-subject" value={subject} onChange={(e) => setSubject(e.target.value)} disabled={sending} className={FIELD} />
                </div>
                <div>
                    <label htmlFor="mail-text" className={FIELD_LABEL}>
                        Message
                    </label>
                    <textarea id="mail-text" value={text} onChange={(e) => setText(e.target.value)} rows={8} disabled={sending} className={TEXTAREA} />
                    <p className="mt-2 text-[13px] text-muted-foreground">From {inbox.address}, to one person: business mail you mean to send, never bulk or cold outreach.</p>
                </div>
                <Failure error={error} />
                <button type="submit" disabled={!ready || sending} className={BUTTON_PRIMARY}>
                    {sending && <Loader2 className="h-4 w-4 animate-spin" />}
                    Send
                </button>
            </form>
        </section>
    );
}
