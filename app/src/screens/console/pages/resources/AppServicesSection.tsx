// An app's email, payments and sign-in, shown inside the Apps drawer. A service whose
// vendor this deployment doesn't hold answers not_available, which its block shows.
// Three compact blocks, each read on its own so one failing leaves the others.
import { useEffect, useState, type ReactNode } from 'react';
import { CreditCard, ExternalLink, KeyRound, Mail } from 'lucide-react';
import { toast } from 'sonner';
import { HAIRLINE } from '@/ui/primitives';
import { cn } from '@/ui/utils';
import type { DnsRecord, EmailSetup, PaymentsSetup, Project, SentEmail, SignInProvider, SignInSetup } from 'noclick';
import type { StatusLook } from '@/screens/console/lib/status';
import { useConsole } from '@/screens/console/hooks/useConsole';
import { invalidateV1, useV1 } from '@/sdk/useV1';
import { Textarea } from '@/ui/textarea';
import { ConsoleButton } from '../../ui/Button';
import { ConsoleDialog } from '../../ui/ConsoleDialog';
import { CopyButton } from '../../ui/CopyButton';
import { ErrorPanel } from '../../ui/ErrorPanel';
import { StatusPill } from '../../ui/StatusPill';
import { TimeCell } from '../../ui/TimeCell';
import { errorText, Field, INPUT, LabeledInput } from './shared';

const MINUTE = 60_000;
const RECENT_SENDS = 5;

const OFF: StatusLook = { label: 'Off', glyph: 'muted', tone: 'muted' };

/** An error inside a block: the block is already the card. */
const FLAT = 'border-0 bg-transparent px-0 py-1';

export function emailLook(setup: EmailSetup): StatusLook {
    if (setup.status === 'active') return { label: 'Active', glyph: 'check', tone: 'ink' };
    if (setup.status === 'pending') return { label: 'Setting up', reason: setup.pendingReason, glyph: 'waiting', tone: 'ink' };
    if (setup.status === 'pending_dns') return { label: 'Waiting', reason: 'DNS records', glyph: 'waiting', tone: 'ink' };
    if (setup.status === 'paused') return { label: 'Paused', reason: setup.pausedReason, glyph: 'cross', tone: 'failure' };
    return OFF;
}

function sentLook(message: SentEmail): StatusLook {
    switch (message.status) {
        case 'delivered':
            return { label: 'Delivered', reason: message.opened ? 'opened' : null, glyph: 'check', tone: 'ink' };
        case 'sent':
            return { label: 'Sent', glyph: 'filled', tone: 'ink' };
        case 'queued':
            return { label: 'Queued', glyph: 'hollow', tone: 'ink' };
        case 'bounced':
            return { label: 'Bounced', glyph: 'cross', tone: 'failure' };
        case 'complained':
            return { label: 'Marked as spam', glyph: 'cross', tone: 'failure' };
        case 'captured':
            return { label: 'Kept', reason: 'preview', glyph: 'hollow', tone: 'ink' };
        default:
            return { label: 'Failed', glyph: 'cross', tone: 'failure' };
    }
}

const CLAIM_STEPS: Record<string, string> = {
    application: 'owner’s application',
    install: 'installing NoClick’s app',
    verification: 'verifying',
};

function paymentsLook(setup: PaymentsSetup): StatusLook {
    if (setup.mode === 'test') return { label: 'Test mode', glyph: 'hollow', tone: 'ink' };
    if (setup.mode === 'claimed') return { label: 'Claimed', reason: CLAIM_STEPS[setup.claimStep ?? ''] ?? null, glyph: 'waiting', tone: 'ink' };
    if (setup.mode === 'live') return { label: 'Live', glyph: 'check', tone: 'ink' };
    if (setup.mode === 'disconnected') return { label: 'Disconnected', glyph: 'cross', tone: 'failure' };
    return OFF;
}

function signInLook(setup: SignInSetup): StatusLook {
    if (setup.status === 'active') return { label: 'Active', glyph: 'check', tone: 'ink' };
    if (setup.status === 'installing') return { label: 'Installing', glyph: 'filled', tone: 'ink' };
    if (setup.status === 'failed') return { label: 'Failed', glyph: 'cross', tone: 'failure' };
    return OFF;
}

const PROVIDERS: readonly { id: SignInProvider; label: string; hint: string }[] = [
    { id: 'email', label: 'Email', hint: 'A one-time code, sent through the app’s email' },
    { id: 'google', label: 'Google', hint: 'Through NoClick, nothing to set up' },
    { id: 'apple', label: 'Apple', hint: 'Through NoClick, nothing to set up' },
    { id: 'microsoft', label: 'Microsoft', hint: 'Work, school and personal accounts, through NoClick' },
    { id: 'github', label: 'GitHub', hint: 'Needs the app’s own GitHub client' },
];

const providerLabel = (id: string) => PROVIDERS.find((p) => p.id === id)?.label ?? id;

/** `6d 19h`, `5h 12m`, `8m`: how long until a link stops working. */
export function timeLeft(ms: number): string {
    const minutes = Math.floor(ms / MINUTE);
    const days = Math.floor(minutes / 1440);
    const hours = Math.floor((minutes % 1440) / 60);
    if (days > 0) return hours ? `${days}d ${hours}h` : `${days}d`;
    if (hours > 0) return `${hours}h ${minutes % 60}m`;
    return `${Math.max(minutes, 1)}m`;
}

/** Re-renders once a minute, so a countdown stays true while the drawer is open. */
function useMinuteTick() {
    const [, tick] = useState(0);
    useEffect(() => {
        const timer = window.setInterval(() => tick((n) => n + 1), MINUTE);
        return () => window.clearInterval(timer);
    }, []);
}

function Block({ title, icon, look, children, actions }: { title: string; icon: ReactNode; look?: StatusLook; children: ReactNode; actions?: ReactNode }) {
    return (
        <section aria-label={title} className={cn('rounded-lg border', HAIRLINE)}>
            <header className={cn('flex h-10 items-center gap-2 border-b px-3', HAIRLINE)}>
                <span className="text-muted-foreground">{icon}</span>
                <h3 className="m-0 flex-1 text-[13px] font-medium">{title}</h3>
                {look && <StatusPill look={look} />}
            </header>
            <div className="flex flex-col gap-3 px-3 py-2.5">{children}</div>
            {actions && <footer className={cn('flex flex-wrap items-center gap-2 border-t px-3 py-2', HAIRLINE)}>{actions}</footer>}
        </section>
    );
}

/** A block's body before its read lands: a skeleton, or the read's error with Retry. */
function pending(read: { loading: boolean; error: unknown; refresh: () => Promise<void> }): ReactNode {
    return read.loading ? <div aria-busy className="h-16 animate-pulse rounded-md bg-foreground/[0.04]" /> : <ErrorPanel error={read.error} onRetry={() => void read.refresh()} className={FLAT} />;
}

/** A value to copy: mono, truncated, the full text on hover. */
function Copyable({ value, label }: { value: string; label: string }) {
    return (
        <span className="group/copy inline-flex min-w-0 max-w-full items-center gap-1">
            <span className="truncate font-mono text-[12px]" title={value}>
                {value}
            </span>
            <CopyButton value={value} label={label} className="opacity-100 md:opacity-0 md:group-hover/copy:opacity-100" />
        </span>
    );
}

function Muted({ children }: { children: ReactNode }) {
    return <p className="m-0 text-[13px] leading-relaxed text-muted-foreground">{children}</p>;
}

function useWrite() {
    const [busy, setBusy] = useState(false);
    const run = async (write: () => Promise<unknown>, done: string) => {
        setBusy(true);
        try {
            await write();
            toast(done);
        } catch (e) {
            toast(errorText(e));
        } finally {
            setBusy(false);
        }
    };
    return { busy, run };
}

// ── email ──────────────────────────────────────────────────────────────────

function SendTestDialog({ project, open, onOpenChange }: { project: Project; open: boolean; onOpenChange: (open: boolean) => void }) {
    const { user } = useConsole();
    const [to, setTo] = useState(user.email ?? '');
    const [subject, setSubject] = useState(`Test from ${project.name}`);
    const [text, setText] = useState(`This is a test message from ${project.name}, sent from the developer console.`);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>(undefined);
    const send = async () => {
        setBusy(true);
        setError(undefined);
        try {
            const sent = await project.email.send({ to: to.trim(), subject, text });
            onOpenChange(false);
            invalidateV1(`projects/${project.id}/email`);
            toast(`Test ${sent.status} to ${to.trim()}`);
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
            title="Send a test email"
            description="Sent from the app's own address, and counted against its daily limit like any other message."
            footer={
                <ConsoleButton variant="primary" disabled={busy || !to.trim() || !subject.trim()} onClick={() => void send()}>
                    {busy ? 'Sending…' : 'Send'}
                </ConsoleButton>
            }
        >
            <div className="flex flex-col gap-3">
                <LabeledInput label="To" id="email-test-to">
                    <input id="email-test-to" type="email" className={INPUT} value={to} onChange={(e) => setTo(e.target.value)} />
                </LabeledInput>
                <LabeledInput label="Subject" id="email-test-subject">
                    <input id="email-test-subject" className={INPUT} value={subject} onChange={(e) => setSubject(e.target.value)} />
                </LabeledInput>
                <LabeledInput label="Message" id="email-test-text">
                    <Textarea id="email-test-text" rows={3} value={text} onChange={(e) => setText(e.target.value)} />
                </LabeledInput>
                {error !== undefined && <ErrorPanel error={error} />}
            </div>
        </ConsoleDialog>
    );
}

function recordLook(record: DnsRecord): StatusLook {
    if (record.status === 'verified') return { label: 'Found', glyph: 'check', tone: 'ink' };
    if (!record.required) return { label: 'Recommended', glyph: 'muted', tone: 'muted' };
    return { label: 'Missing', glyph: 'waiting', tone: 'ink' };
}

function DnsRecords({ setup }: { setup: EmailSetup }) {
    return (
        <div className="flex flex-col gap-1.5">
            <Muted>
                Add these where <span className="font-mono text-[12px] text-foreground">{setup.domain}</span>’s DNS is hosted. Email turns on within minutes of public DNS answering with each one, and broadcasts once their own records answer.
            </Muted>
            <ul aria-label="DNS records" className={cn('m-0 list-none rounded-md border p-0', HAIRLINE)}>
                {setup.records.map((r) => (
                    <li key={`${r.type}-${r.name}`} className={cn('flex flex-col gap-0.5 px-2.5 py-1.5')}>
                        <span className="flex items-center gap-2 text-[13px]">
                            <span className="w-12 shrink-0 font-mono text-[12px]">{r.type}</span>
                            <span className="min-w-0 flex-1 truncate font-mono text-[12px]" title={r.name}>
                                {r.name}
                            </span>
                            {r.purpose && <span className="hidden text-[12px] text-muted-foreground sm:inline">{r.purpose}</span>}
                            <StatusPill look={recordLook(r)} />
                        </span>
                        <span className="pl-14">
                            <Copyable value={r.value} label={`Copy the ${r.purpose ?? r.type} value`} />
                        </span>
                    </li>
                ))}
            </ul>
        </div>
    );
}

function RecentSends({ project }: { project: Project }) {
    const sends = useV1(`projects/${project.id}/email/messages`, () => project.email.messages({ limit: RECENT_SENDS }));
    if (sends.error !== undefined) return <ErrorPanel error={sends.error} onRetry={() => void sends.refresh()} className={FLAT} />;
    if (sends.loading) return <div aria-busy className="h-20 animate-pulse rounded-md bg-foreground/[0.04]" />;
    const rows = sends.data ?? [];
    if (!rows.length) return <Muted>Nothing sent yet.</Muted>;
    return (
        <ul aria-label="Recent sends" className={cn('m-0 list-none rounded-md border p-0', HAIRLINE)}>
            {rows.map((m) => (
                <li key={m.id} className={cn('flex flex-wrap items-center gap-x-3 gap-y-0.5 px-2.5 py-1.5 text-[13px]')}>
                    <span className="w-full min-w-0 truncate sm:w-40 sm:shrink-0">{m.to.join(', ')}</span>
                    <span className="min-w-0 flex-1 truncate text-muted-foreground" title={m.error ?? undefined}>
                        {m.subject ?? '(no subject)'}
                    </span>
                    <StatusPill look={sentLook(m)} />
                    <TimeCell value={m.at} className="w-16 text-right text-[12px] text-muted-foreground" />
                </li>
            ))}
        </ul>
    );
}

function Broadcasts({ setup: s }: { setup: EmailSetup }) {
    if (s.broadcastStatus === 'needs_domain') return <span className="text-muted-foreground">Need a domain of your own; they go from its own subdomain, apart from the sends above.</span>;
    if (s.broadcastStatus === 'pending') return <span className="text-muted-foreground">Setting up, as for the sends above.</span>;
    if (s.broadcastStatus === 'pending_dns') return <span className="text-muted-foreground">Waiting for the records of {s.broadcastFromAddress?.split('@')[1] ?? 'their subdomain'}.</span>;
    if (s.broadcastStatus === 'paused') return <span className="text-red-600 dark:text-red-400">Paused{s.broadcastPausedReason ? `: ${s.broadcastPausedReason}` : ''}</span>;
    return (
        <span className="flex min-w-0 flex-col">
            {s.broadcastFromAddress && <span className="font-mono text-[12px]">{s.broadcastFromAddress}</span>}
            <span className="tabular-nums">{`${(s.broadcastSentToday ?? 0).toLocaleString()} of ${(s.broadcastDailyLimit ?? 0).toLocaleString()} recipients today`}</span>
            {s.postalAddress ? (
                <span className="text-[12px] text-muted-foreground">Footer address: {s.postalAddress}</span>
            ) : (
                <span className="text-[12px] text-muted-foreground">
                    Needs a postal address for the footer: <span className="font-mono text-[12px]">app.email.enable(postal_address=...)</span>
                </span>
            )}
        </span>
    );
}

function EmailBlock({ project }: { project: Project }) {
    const setup = useV1(`projects/${project.id}/email`, () => project.email.status());
    const [testing, setTesting] = useState(false);
    const write = useWrite();
    const icon = <Mail className="h-3.5 w-3.5" />;
    const s = setup.data;
    if (!s)
        return (
            <Block title="Email" icon={icon}>
                {pending(setup)}
            </Block>
        );
    if (s.status === 'off') {
        return (
            <Block
                title="Email"
                icon={icon}
                look={OFF}
                actions={
                    <ConsoleButton
                        size="sm"
                        disabled={write.busy}
                        onClick={() =>
                            void write.run(async () => {
                                setup.mutate(await project.email.enable());
                            }, `Email is on for ${project.name}`)
                        }
                    >
                        Turn on email
                    </ConsoleButton>
                }
            >
                <Muted>Transactional email from the app’s own address: receipts, confirmations, sign-in codes. Turn it on with the default sender, or from your code on your own domain.</Muted>
            </Block>
        );
    }
    return (
        <Block
            title="Email"
            icon={icon}
            look={emailLook(s)}
            actions={
                <ConsoleButton size="sm" disabled={s.status !== 'active'} title={s.status === 'active' ? undefined : 'Email sends once it is active.'} onClick={() => setTesting(true)}>
                    Send a test
                </ConsoleButton>
            }
        >
            <dl className="m-0">
                <Field label="Sender">
                    {s.fromAddress ? (
                        <span className="flex min-w-0 max-w-full flex-wrap items-baseline gap-x-1.5">
                            {s.fromName && <span>{s.fromName}</span>}
                            <Copyable value={s.fromAddress} label="Copy the sender address" />
                        </span>
                    ) : (
                        '—'
                    )}
                </Field>
                <Field label="Domain">{s.domain ? <span className="font-mono text-[12px]">{s.domain}</span> : <span className="text-muted-foreground">Default sender</span>}</Field>
                {s.dailyLimit != null && (
                    <Field label="Today">
                        <span className="tabular-nums">
                            {(s.sentToday ?? 0).toLocaleString()} of {s.dailyLimit.toLocaleString()} sent
                        </span>
                    </Field>
                )}
                <Field label="Broadcasts">
                    <Broadcasts setup={s} />
                </Field>
            </dl>
            {(s.status === 'pending_dns' || s.broadcastStatus === 'pending_dns') && s.records.length > 0 && <DnsRecords setup={s} />}
            {s.status === 'paused' && <p className="m-0 text-[13px] text-red-600 dark:text-red-400">Sending is paused{s.pausedReason ? `: ${s.pausedReason}` : ''}. Clean up the addresses you send to, then contact support to resume.</p>}
            <div className="flex flex-col gap-1.5">
                <h4 className="m-0 text-[12px] font-medium text-muted-foreground">Recent sends</h4>
                <RecentSends project={project} />
            </div>
            {testing && <SendTestDialog project={project} open={testing} onOpenChange={setTesting} />}
        </Block>
    );
}

// ── payments ───────────────────────────────────────────────────────────────

function ClaimLink({ setup, onReopen, busy }: { setup: PaymentsSetup; onReopen: () => void; busy: boolean }) {
    const { now } = useConsole();
    useMinuteTick();
    const left = setup.testExpiresAt ? setup.testExpiresAt.getTime() - now() : null;
    if (left !== null && left <= 0) {
        return (
            <div className="flex flex-wrap items-center gap-2">
                <span className="text-[13px] text-muted-foreground">The test account expired unclaimed, with its test data.</span>
                <ConsoleButton size="sm" disabled={busy} onClick={onReopen}>
                    Open a fresh test account
                </ConsoleButton>
            </div>
        );
    }
    return (
        <div className="flex min-w-0 flex-col gap-0.5">
            {setup.claimUrl && <Copyable value={setup.claimUrl} label="Copy the claim link" />}
            {left !== null && setup.testExpiresAt && (
                <span className="text-[12px] tabular-nums text-muted-foreground">
                    Expires in {timeLeft(left)} unless claimed · <TimeCell value={setup.testExpiresAt} tier="absolute" />
                </span>
            )}
        </div>
    );
}

function EnablePaymentsDialog({ project, open, onOpenChange, onEnabled }: { project: Project; open: boolean; onOpenChange: (open: boolean) => void; onEnabled: (setup: PaymentsSetup) => void }) {
    const [country, setCountry] = useState('');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>(undefined);
    const code = country.trim().toUpperCase();
    const submit = async () => {
        setBusy(true);
        setError(undefined);
        try {
            onEnabled(await project.payments.enable({ country: code }));
            onOpenChange(false);
            toast(`Test payments are on for ${project.name}`);
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
            title="Turn on test payments"
            description="The account can only ever be in the country of the owner’s business."
            footer={
                <ConsoleButton variant="primary" disabled={busy || !/^[A-Z]{2}$/.test(code)} onClick={() => void submit()}>
                    {busy ? 'Opening…' : 'Open the test account'}
                </ConsoleButton>
            }
        >
            <div className="flex flex-col gap-3">
                <LabeledInput label="Country (two letters)" id="payments-country">
                    <input id="payments-country" className={cn(INPUT, 'w-20 font-mono uppercase')} maxLength={2} value={country} onChange={(e) => setCountry(e.target.value)} placeholder="US" />
                </LabeledInput>
                {error !== undefined && <ErrorPanel error={error} />}
            </div>
        </ConsoleDialog>
    );
}

function PaymentsBlock({ project }: { project: Project }) {
    const setup = useV1(`projects/${project.id}/payments`, () => project.payments.status());
    const [opening, setOpening] = useState(false);
    const write = useWrite();
    const icon = <CreditCard className="h-3.5 w-3.5" />;
    const s = setup.data;
    if (!s)
        return (
            <Block title="Payments" icon={icon}>
                {pending(setup)}
            </Block>
        );
    if (s.mode === 'off') {
        return (
            <Block
                title="Payments"
                icon={icon}
                look={OFF}
                actions={
                    <ConsoleButton size="sm" onClick={() => setOpening(true)}>
                        Turn on test payments
                    </ConsoleButton>
                }
            >
                <Muted>Take payments without an account of your own. NoClick opens a test account for the app and puts its keys in the app’s secrets; the owner claims it to take real money.</Muted>
                {opening && <EnablePaymentsDialog project={project} open={opening} onOpenChange={setOpening} onEnabled={(next) => setup.mutate(next)} />}
            </Block>
        );
    }
    const enableAgain = (done: string) =>
        void write.run(async () => {
            setup.mutate(await project.payments.enable({ country: s.country ?? undefined }));
        }, done);
    return (
        <Block
            title="Payments"
            icon={icon}
            look={paymentsLook(s)}
            actions={
                s.mode === 'disconnected' ? (
                    <ConsoleButton size="sm" disabled={write.busy} onClick={() => enableAgain('Live payments are reconnected')}>
                        Reconnect
                    </ConsoleButton>
                ) : s.dashboardUrl ? (
                    <a href={s.dashboardUrl} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-[13px] font-medium text-foreground hover:underline">
                        Owner’s payments dashboard <ExternalLink className="h-3 w-3" />
                    </a>
                ) : undefined
            }
        >
            <dl className="m-0">
                {s.processor && (
                    <Field label="Processor">
                        <span className="font-mono text-[12px]">{s.processor}</span>
                        <span className="text-muted-foreground"> · the client library the app&apos;s code uses</span>
                    </Field>
                )}
                {(s.mode === 'test' || s.mode === 'claimed') && (
                    <Field label="Claim link">
                        <ClaimLink setup={s} busy={write.busy} onReopen={() => enableAgain('A fresh test account is ready')} />
                    </Field>
                )}
                {s.country && <Field label="Country">{s.country}</Field>}
                <Field label="Keys in secrets">
                    {s.secrets.length ? (
                        <span className="flex flex-wrap gap-1">
                            {s.secrets.map((name) => (
                                <span key={name} className="rounded-[5px] bg-foreground/[0.06] px-1.5 py-px font-mono text-[12px] text-foreground/75">
                                    {name}
                                </span>
                            ))}
                        </span>
                    ) : (
                        '—'
                    )}
                </Field>
            </dl>
            {s.mode === 'test' && (
                <Muted>
                    Only test cards work until the account is claimed. Claiming makes it the owner’s: they sign in with the payment processor, add their business and bank details and install NoClick’s payments app. Payments then go straight to them; NoClick takes no cut and never holds the money.
                </Muted>
            )}
            {s.mode !== 'test' && s.nextStep && <Muted>{s.nextStep}</Muted>}
            {s.mode === 'live' && <Muted>Previews keep the test keys, so only production takes real payments. Refunds, disputes and payouts are handled in the owner’s dashboard.</Muted>}
        </Block>
    );
}

// ── sign-in ────────────────────────────────────────────────────────────────

function EnableSignInDialog({ project, current, open, onOpenChange, onStarted }: { project: Project; current: SignInSetup; open: boolean; onOpenChange: (open: boolean) => void; onStarted: () => void }) {
    const [providers, setProviders] = useState<SignInProvider[]>(current.providers.length ? (current.providers as SignInProvider[]) : ['email']);
    const [branch, setBranch] = useState('');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>(undefined);
    const changing = current.status !== 'off';
    const start = async () => {
        setBusy(true);
        setError(undefined);
        try {
            const op = await project.signIn.enable(providers, { branch: branch.trim() || undefined });
            onOpenChange(false);
            onStarted();
            toast(`Adding sign-in to ${project.name}`, { description: `Operation ${op.id}` });
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
            title={changing ? 'Change sign-in' : 'Enable sign-in'}
            description="This commits code to the app’s repo and deploys it."
            footer={
                <>
                    <ConsoleButton variant="ghost" onClick={() => onOpenChange(false)}>
                        Cancel
                    </ConsoleButton>
                    <ConsoleButton variant="primary" disabled={busy || providers.length === 0} onClick={() => void start()}>
                        {busy ? 'Starting…' : 'Commit and deploy'}
                    </ConsoleButton>
                </>
            }
        >
            <div className="flex flex-col gap-4">
                <fieldset className="m-0 flex flex-col gap-2 border-0 p-0">
                    <legend className="mb-1.5 p-0 text-[12px] font-medium text-muted-foreground">Sign in with</legend>
                    {PROVIDERS.map((p) => (
                        <label key={p.id} className="flex cursor-pointer items-baseline gap-2 text-[13px]">
                            <input
                                type="checkbox"
                                checked={providers.includes(p.id)}
                                onChange={(e) => setProviders((list) => (e.target.checked ? [...list, p.id] : list.filter((x) => x !== p.id)))}
                                className="translate-y-px accent-[hsl(var(--foreground))]"
                            />
                            <span className="font-medium">{p.label}</span>
                            <span className="text-[12px] text-muted-foreground">{p.hint}</span>
                        </label>
                    ))}
                </fieldset>
                <LabeledInput label="Branch (optional)" id="sign-in-branch">
                    <input id="sign-in-branch" className={cn(INPUT, 'font-mono')} value={branch} onChange={(e) => setBranch(e.target.value)} placeholder="The production branch" />
                </LabeledInput>
                <div className={cn('rounded-md border bg-foreground/[0.02] px-3 py-2.5', HAIRLINE)}>
                    <p className="m-0 mb-1.5 text-[12px] font-medium">What happens</p>
                    <ul className="m-0 flex list-disc flex-col gap-1 pl-4 text-[13px] text-muted-foreground">
                        <li>Sign-in code for the app’s framework is committed to its repo{branch.trim() ? <> on <span className="font-mono text-[12px] text-foreground">{branch.trim()}</span></> : ' on the production branch'}.</li>
                        <li>
                            A <span className="font-mono text-[12px] text-foreground">{current.usersTable ?? 'users'}</span> table, with tables for its sessions, linked accounts and codes, is created in the app’s bound database.
                        </li>
                        <li>{branch.trim() ? 'The branch gets a preview deployment to review before you merge.' : 'Production is deployed, so sign-in goes live.'}</li>
                        <li>The code is yours: read it, change it, and it keeps working if you export the app. A later change never overwrites a file you edited; it goes on a branch of its own.</li>
                    </ul>
                </div>
                {error !== undefined && <ErrorPanel error={error} />}
            </div>
        </ConsoleDialog>
    );
}

function SignInBlock({ project }: { project: Project }) {
    const setup = useV1(`projects/${project.id}/sign_in`, () => project.signIn.status());
    const [editing, setEditing] = useState(false);
    const write = useWrite();
    const icon = <KeyRound className="h-3.5 w-3.5" />;
    const s = setup.data;
    if (!s)
        return (
            <Block title="Sign-in" icon={icon}>
                {pending(setup)}
            </Block>
        );
    const off = s.status === 'off';
    const available = s.status === 'active' ? s.updateAvailable : null;
    const upgrade = (to: string) =>
        void write.run(async () => {
            await project.signIn.upgrade();
            invalidateV1(`projects/${project.id}/sign_in`);
        }, `Upgrading sign-in to ${to}`);
    return (
        <Block
            title="Sign-in"
            icon={icon}
            look={signInLook(s)}
            actions={
                <>
                    {available && (
                        <ConsoleButton size="sm" variant="ghost" disabled={write.busy} onClick={() => upgrade(available)}>
                            Upgrade
                        </ConsoleButton>
                    )}
                    <ConsoleButton size="sm" disabled={s.status === 'installing'} onClick={() => setEditing(true)}>
                        {off ? 'Enable sign-in' : 'Change providers'}
                    </ConsoleButton>
                </>
            }
        >
            {off ? (
                <Muted>Accounts for the app’s own users, by email code, Google, Apple or Microsoft. Enabling it commits the sign-in code to the app’s repo and keeps the users in its own database.</Muted>
            ) : (
                <>
                    <dl className="m-0">
                        <Field label="Providers">{s.providers.length ? s.providers.map(providerLabel).join(', ') : '—'}</Field>
                        {s.managedProviders.length > 0 && (
                            <Field label="Through NoClick">
                                {s.managedProviders.map(providerLabel).join(', ')} <span className="text-muted-foreground">· nothing to set up</span>
                            </Field>
                        )}
                        <Field label="Users">{s.usersTable ? <span className="font-mono text-[12px]">{s.usersTable}</span> : '—'} <span className="text-muted-foreground">in the app’s database</span></Field>
                        {s.commit && (
                            <Field label="Commit">
                                <span className="font-mono text-[12px]">{s.commit.slice(0, 7)}</span>
                                {s.branch && <span className="text-muted-foreground"> on <span className="font-mono text-[12px] text-foreground">{s.branch}</span></span>}
                            </Field>
                        )}
                        {s.library && s.version && (
                            <Field label="Library">
                                <span className="font-mono text-[12px]">
                                    {s.library} {s.version}
                                </span>
                                {s.updateAvailable && <span className="text-muted-foreground"> · {s.updateAvailable} available</span>}
                            </Field>
                        )}
                        {Object.entries(s.callbackUrls).map(([provider, url]) => (
                            <Field key={provider} label={`${providerLabel(provider)} callback`}>
                                <Copyable value={url} label={`Copy the ${providerLabel(provider)} callback URL`} />
                            </Field>
                        ))}
                    </dl>
                    {s.missingSecrets.length > 0 && (
                        <p className="m-0 text-[13px] text-muted-foreground">
                            Set <span className="font-mono text-[12px] text-foreground">{s.missingSecrets.join(', ')}</span> in the app’s secrets to finish its providers; until then, those buttons say they aren’t configured.
                        </p>
                    )}
                    {s.editedFiles.length > 0 && (
                        <p className="m-0 text-[13px] text-muted-foreground">
                            You edited <span className="font-mono text-[12px] text-foreground">{s.editedFiles.join(', ')}</span>, so the last change went to its own branch for you to merge.
                        </p>
                    )}
                    {s.status === 'installing' && <Muted>Committing the code and deploying. This takes a minute or two.</Muted>}
                </>
            )}
            {editing && <EnableSignInDialog project={project} current={s} open={editing} onOpenChange={setEditing} onStarted={() => invalidateV1(`projects/${project.id}/sign_in`)} />}
        </Block>
    );
}

export function AppServicesSection({ project }: { project: Project }) {
    return (
        <div className="flex flex-col gap-3">
            <EmailBlock project={project} />
            <PaymentsBlock project={project} />
            <SignInBlock project={project} />
        </div>
    );
}
