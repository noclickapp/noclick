// One user, by your id for them, in the anatomy every detail page shares: what
// runs for them now, their connections, their recent runs and the code that acts
// for them; beside them who they are (spend against their cap and contact,
// editable) and what they have (their own agents, inboxes, numbers and rules).
// Every read filters by user_id, so a suspended user still loads; writes that
// act for them are disabled while they're suspended. Their spending too: paused
// or not, what they're told and what waits, and pause and resume.
import { useEffect, useState, type ReactNode } from 'react';
import { Link, useNavigate } from 'react-router';
import { Bot, FlaskConical, Inbox as InboxIcon, Phone, ShieldCheck } from 'lucide-react';
import { toast } from 'sonner';
import { HAIRLINE, LiveDot } from '@/ui/primitives';
import { Input } from '@/ui/input';
import { Textarea } from '@/ui/textarea';
import { cn } from '@/ui/utils';
import { Agent, Inbox, Operation, PhoneNumber, Policy, User, type Session } from 'noclick';
import { formatDuration, formatCount } from '@/screens/console/lib/format';
import { userPath } from '@/screens/console/lib/userFilter';
import { snippetTabs, userCodeSnippet } from '@/screens/console/lib/snippets';
import { useAccount, useConsole, useConsoleHref } from '@/screens/console/hooks/useConsole';
import { invalidateV1, useV1 } from '@/sdk/useV1';
import { useReportHeld } from '@/sdk/held';
import { useSearchParam } from '@/screens/console/hooks/useQueryState';
import { recordRecent } from '@/screens/console/hooks/useRecent';
import type { ConsolePageProps } from '../sections';
import { ConnectionsTable } from '../connections';
import { NewInCode } from '../NewInCode';
import { SWITCH_ROWS, SwitchRow } from '../ui/SwitchRow';
import { scopeWords } from '@/screens/console/lib/scopes';
import { ConsoleButton } from '../ui/Button';
import { CodeSnippet } from '../ui/CodeSnippet';
import { ConsoleDialog } from '../ui/ConsoleDialog';
import { AsideSection, DetailLayout, Fact, Facts } from '../ui/Detail';
import { ErrorPanel } from '../ui/ErrorPanel';
import { CopyIdChip } from '../ui/IdChip';
import { JsonView } from '../ui/JsonView';
import { PageHeader, PageSection } from '../ui/PageHeader';
import { RevealOnceSecret } from '../ui/RevealOnceSecret';
import { StatusPill } from '../ui/StatusPill';
import { TimeCell } from '../ui/TimeCell';
import { OperationsView } from './Operations';
import { FormField, INPUT, MoreMenu, SpendReadError, UserSpend, formError, parseUsd, spendOf, userStatusLook, useUserSpend } from './Users';

export const SUSPENDED_REASON = 'Suspended users are read-only: reactivate them to act for them.';

/** The session TTL bounds the API enforces (60s to 24h), in minutes for the form. */
export const SESSION_TTL_MINUTES = { min: 1, max: 24 * 60, default: 60 } as const;

const LIST_LIMIT = 200;

const Dash = () => <span className="text-muted-foreground">None</span>;

function EditLink({ label, onClick }: { label: string; onClick: () => void }) {
    return (
        <button type="button" onClick={onClick} className="shrink-0 whitespace-nowrap text-[12px] text-muted-foreground transition-colors hover:text-foreground">
            {label}
        </button>
    );
}

// ── about ──────────────────────────────────────────────────────────────────

function SpendFact({ user, onSaved }: { user: User; onSaved: (u: User) => void }) {
    const spend = useUserSpend();
    const [editing, setEditing] = useState(false);
    const [cap, setCap] = useState('');
    const [error, setError] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);
    const start = () => {
        setCap(user.spendCapUsdPerMonth == null ? '' : String(user.spendCapUsdPerMonth));
        setError(null);
        setEditing(true);
    };
    const save = async () => {
        const parsed = parseUsd(cap);
        if (parsed.error) return setError(parsed.error);
        setBusy(true);
        try {
            onSaved(await user.update({ spendCapUsdPerMonth: parsed.value }));
            invalidateV1('users');
            toast.success(parsed.value === null ? 'Cap removed' : 'Cap saved');
            setEditing(false);
        } catch (e) {
            setError(formError(e).message);
        } finally {
            setBusy(false);
        }
    };
    return (
        <Fact label="This month">
            {editing ? (
                <form
                    className="flex flex-col gap-2"
                    onSubmit={(e) => {
                        e.preventDefault();
                        void save();
                    }}
                >
                    <FormField label="Monthly cap (USD)" htmlFor="user-cap-edit" error={error} hint="Blank removes the cap.">
                        <Input id="user-cap-edit" inputMode="decimal" className={cn(INPUT, 'tabular-nums')} value={cap} onChange={(e) => setCap(e.target.value)} />
                    </FormField>
                    <div className="flex gap-2">
                        <ConsoleButton size="sm" type="submit" variant="soft" disabled={busy}>
                            Save
                        </ConsoleButton>
                        <ConsoleButton size="sm" variant="ghost" onClick={() => setEditing(false)}>
                            Cancel
                        </ConsoleButton>
                    </div>
                </form>
            ) : (
                <div className="flex flex-col gap-1.5">
                    <div className="flex items-start justify-between gap-2">
                        <UserSpend spent={spendOf(spend, user.id)} cap={user.spendCapUsdPerMonth} noCapLabel className="w-full" />
                        <EditLink label="Edit cap" onClick={start} />
                    </div>
                    <SpendReadError spend={spend} />
                </div>
            )}
        </Fact>
    );
}

type ContactField = 'name' | 'email' | 'phone' | 'timezone';

/** What the contact form edits. */
const CONTACT_FIELDS: readonly ContactField[] = ['name', 'email', 'phone', 'timezone'];

const CONTACT_LABELS: Record<ContactField, string> = { name: 'Name', email: 'Email', phone: 'Phone', timezone: 'Timezone' };

function ContactFacts({ user, onSaved }: { user: User; onSaved: (u: User) => void }) {
    const [draft, setDraft] = useState<Record<ContactField, string> | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);
    const save = async () => {
        if (!draft) return;
        setBusy(true);
        try {
            // Blank clears a field.
            onSaved(
                await user.update({
                    name: draft.name.trim() || null,
                    email: draft.email.trim() || null,
                    phone: draft.phone.trim() || null,
                    timezone: draft.timezone.trim() || null,
                }),
            );
            invalidateV1('users');
            toast.success('Contact saved');
            setDraft(null);
        } catch (e) {
            setError(formError(e).message);
        } finally {
            setBusy(false);
        }
    };
    if (draft) {
        return (
            <form
                aria-label="Contact"
                className="flex flex-col gap-3 py-1.5"
                onSubmit={(e) => {
                    e.preventDefault();
                    void save();
                }}
            >
                {CONTACT_FIELDS.map((f) => (
                    <FormField
                        key={f}
                        label={CONTACT_LABELS[f]}
                        htmlFor={`user-edit-${f}`}
                        hint={f === 'timezone' ? 'An IANA name, like America/New_York. Blank is UTC.' : undefined}
                    >
                        <Input
                            id={`user-edit-${f}`}
                            className={INPUT}
                            value={draft[f]}
                            placeholder={f === 'timezone' ? 'America/New_York' : undefined}
                            onChange={(e) => setDraft({ ...draft, [f]: e.target.value })}
                        />
                    </FormField>
                ))}
                {error && <p className="m-0 text-[12px] text-red-600 dark:text-red-400">{error}</p>}
                <div className="flex gap-2">
                    <ConsoleButton size="sm" type="submit" variant="soft" disabled={busy}>
                        Save
                    </ConsoleButton>
                    <ConsoleButton size="sm" variant="ghost" onClick={() => setDraft(null)}>
                        Cancel
                    </ConsoleButton>
                </div>
            </form>
        );
    }
    const edit = () => {
        setError(null);
        setDraft({ name: user.name ?? '', email: user.email ?? '', phone: user.phone ?? '', timezone: user.timezone ?? '' });
    };
    return (
        <>
            <Fact label="Contact">
                <div className="flex items-start justify-between gap-2">
                    <span className="flex min-w-0 flex-col">
                        {user.name && <span className="truncate">{user.name}</span>}
                        <span className="truncate">{user.email ?? <span className="text-muted-foreground">No email</span>}</span>
                        {user.phone && (
                            <span className="truncate">
                                <span className="font-mono text-[12px]">{user.phone}</span>
                                <span className="text-muted-foreground"> · {user.phoneVerifiedAt ? 'verified' : 'not verified'}</span>
                            </span>
                        )}
                    </span>
                    <EditLink label="Edit" onClick={edit} />
                </div>
            </Fact>
            <Fact label="Timezone">
                {user.timezone ? <span className="font-mono text-[12px]">{user.timezone}</span> : <span className="text-muted-foreground">UTC (none set)</span>}
            </Fact>
            {user.phone && !user.phoneVerifiedAt && (
                <p className="m-0 pb-1.5 text-[12px] text-muted-foreground">
                    {'The code goes to your user’s phone, so verify it from your server: '}
                    <span className="font-mono text-foreground/85">user.verify_phone()</span>, then <span className="font-mono text-foreground/85">user.check_phone(code)</span> with the code
                    they type.
                </p>
            )}
        </>
    );
}

/** Whether your billing has paused what they can spend. */
function SpendingFact({ user, onPause, onResume }: { user: User; onPause: () => void; onResume: () => void }) {
    const paused = user.spending?.paused === true;
    return (
        <Fact label="Spending">
            <div className="flex items-start justify-between gap-2">
                <span>
                    {paused ? (
                        <>
                            Paused <TimeCell value={user.spending?.since ?? null} />
                        </>
                    ) : (
                        'Active'
                    )}
                </span>
                <EditLink label={paused ? 'Resume' : 'Pause'} onClick={paused ? onResume : onPause} />
            </div>
        </Fact>
    );
}

function About({ user, onSaved, spending }: { user: User; onSaved: (u: User) => void; spending: { onPause: () => void; onResume: () => void } }) {
    const metadata = user.metadata && Object.keys(user.metadata).length ? user.metadata : null;
    return (
        <AsideSection title="About">
            <Facts>
                <SpendFact user={user} onSaved={onSaved} />
                <SpendingFact user={user} onPause={spending.onPause} onResume={spending.onResume} />
                <ContactFacts user={user} onSaved={onSaved} />
                <Fact label="ID">
                    <CopyIdChip id={user.id} />
                </Fact>
                <Fact label="Created">
                    <TimeCell value={user.createdAt} tier="absolute" />
                </Fact>
                <Fact label="Metadata">{metadata ? <JsonView value={metadata} /> : <Dash />}</Fact>
            </Facts>
        </AsideSection>
    );
}

// ── uses ───────────────────────────────────────────────────────────────────

const plural = (n: number, one: string, many = `${one}s`) => `${formatCount(n)} ${n === 1 ? one : many}`;

function UseRow({ to, icon, children }: { to: string; icon: ReactNode; children: ReactNode }) {
    return (
        <li>
            <Link to={to} className="flex items-center gap-2 py-2 text-[13px] text-foreground/85 transition-colors hover:text-foreground">
                <span className="shrink-0 text-muted-foreground">{icon}</span>
                <span className="min-w-0 truncate">{children}</span>
            </Link>
        </li>
    );
}

function Uses({ user }: { user: User }) {
    const { client } = useConsole();
    const href = useConsoleHref();
    const agents = useV1(`agents?user=${user.id}`, () => Agent.list({ client, userFilter: user.id, limit: LIST_LIMIT }));
    const inboxes = useV1(`inboxes?user=${user.id}`, () => Inbox.list({ client, userFilter: user.id, limit: LIST_LIMIT }));
    const numbers = useV1(`phone_numbers?user=${user.id}`, () => PhoneNumber.list({ client, userFilter: user.id, limit: LIST_LIMIT }));
    const rules = useV1(`policy?${user.id}`, () => Policy.get({ client, user: user.id }));
    const own = (agents.data ?? []).filter((a) => a.userId === user.id);
    const ruleCount = rules.data ? rules.data.allow.length + rules.data.deny.length + rules.data.requireApproval.length : 0;
    const loaded = agents.data && inboxes.data && numbers.data;
    const empty = loaded && !own.length && !inboxes.data!.length && !numbers.data!.length;
    return (
        <AsideSection title="Has">
            {!loaded ? (
                <div aria-busy className="h-16 animate-pulse rounded-lg bg-foreground/[0.03]" />
            ) : (
                <ul aria-label="What they have" className={'m-0 list-none p-0'}>
                    {own.map((a) => (
                        <UseRow key={a.id} to={href(`agents/${a.id}`)} icon={<Bot className="h-3.5 w-3.5" />}>
                            {a.name}
                        </UseRow>
                    ))}
                    {inboxes.data!.map((i) => (
                        <UseRow key={i.id} to={href('resources/inboxes', { inbox: i.id })} icon={<InboxIcon className="h-3.5 w-3.5" />}>
                            <span className="font-mono">{i.address}</span>
                        </UseRow>
                    ))}
                    {numbers.data!.map((n) => (
                        <UseRow key={n.id} to={href('resources/phone', { number: n.id })} icon={<Phone className="h-3.5 w-3.5" />}>
                            <span className="font-mono">{n.number}</span>
                        </UseRow>
                    ))}
                    <UseRow to={href('settings/policy', { layer: user.id })} icon={<ShieldCheck className="h-3.5 w-3.5" />}>
                        {rules.data ? (ruleCount ? `${plural(ruleCount, 'approval rule')} of their own` : 'No approval rules of their own') : 'Approval rules'}
                    </UseRow>
                </ul>
            )}
            {empty && <p className="m-0 mt-1 text-[12px] text-muted-foreground">Account agents serve them too, in conversations of their own.</p>}
        </AsideSection>
    );
}

// ── now ────────────────────────────────────────────────────────────────────

function Now({ user }: { user: User }) {
    const { client } = useConsole();
    const [, setOp] = useSearchParam('op');
    const running = useV1(`operations?user-running=${user.id}`, () => Operation.listPage({ client, status: 'live', userFilter: user.id, limit: 20 }), { pollMs: 10_000 });
    const rows = running.data?.data ?? [];
    return (
        <PageSection title="Now" count={rows.length}>
            {running.error !== undefined && !running.data ? (
                <ErrorPanel error={running.error} onRetry={() => void running.refresh()} />
            ) : !running.data ? (
                <div aria-busy className="h-10 animate-pulse rounded-lg bg-foreground/[0.03]" />
            ) : rows.length ? (
                <ul aria-label="Running now" className={'m-0 list-none p-0'}>
                    {rows.map((op) => (
                        <li key={op.id}>
                            <button
                                type="button"
                                onClick={() => setOp(op.id, { push: true })}
                                className="-mx-3 flex w-[calc(100%+1.5rem)] items-center gap-3 rounded-lg px-3 py-2.5 text-left transition-colors hover:bg-foreground/[0.03]"
                            >
                                <LiveDot className="scale-75" />
                                <span className="min-w-0 flex-1 truncate text-[14px] text-foreground">{op.summaryText || op.kind}</span>
                                <span className="hidden shrink-0 font-mono text-[12px] text-muted-foreground sm:inline">{op.kind}</span>
                                <TimeCell value={op.createdAt} className="shrink-0 text-[13px] text-muted-foreground" />
                            </button>
                        </li>
                    ))}
                </ul>
            ) : (
                <p className="m-0 text-[13px] text-muted-foreground">Nothing running for this user right now.</p>
            )}
        </PageSection>
    );
}

// ── dialogs ────────────────────────────────────────────────────────────────

function MintSessionDialog({ user, open, onOpenChange }: { user: User; open: boolean; onOpenChange: (open: boolean) => void }) {
    const sessionScopes = useAccount().data?.meta.session_scopes ?? [];
    const [scopes, setScopes] = useState<string[] | null>(null);
    const [minutes, setMinutes] = useState(String(SESSION_TTL_MINUTES.default));
    const [error, setError] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);
    const [session, setSession] = useState<Session | null>(null);
    const chosen = scopes ?? sessionScopes;

    const mint = async () => {
        const m = Number(minutes);
        if (!Number.isInteger(m) || m < SESSION_TTL_MINUTES.min || m > SESSION_TTL_MINUTES.max) return setError('Between 1 minute and 24 hours (1440 minutes).');
        if (!chosen.length) return setError('Pick at least one scope.');
        setBusy(true);
        setError(null);
        try {
            setSession(await user.session({ scopes: chosen, ttlS: m * 60 }));
            onOpenChange(false);
        } catch (e) {
            setError(formError(e).message);
        } finally {
            setBusy(false);
        }
    };
    const done = () => {
        setSession(null);
        setScopes(null);
        setMinutes(String(SESSION_TTL_MINUTES.default));
    };
    return (
        <>
            <ConsoleDialog
                open={open}
                onOpenChange={onOpenChange}
                mark={<FlaskConical aria-hidden className="h-5 w-5" />}
                title={`Test session for ${user.id}`}
                description="A short-lived token to try your frontend as them. In production, your server makes sessions."

                footer={
                    <>
                        <ConsoleButton variant="ghost" onClick={() => onOpenChange(false)}>
                            Cancel
                        </ConsoleButton>
                        <ConsoleButton variant="primary" onClick={mint} disabled={busy}>
                            Make session
                        </ConsoleButton>
                    </>
                }
            >
                <div className="flex flex-col gap-4">
                    <section aria-label="What it may do">
                        <h3 className="m-0 text-[12px] font-medium text-muted-foreground">What it may do</h3>
                        <ul className={SWITCH_ROWS}>
                            {sessionScopes.map((sc) => (
                                <li key={sc}>
                                    <SwitchRow
                                        label={scopeWords(sc)}
                                        id={sc}
                                        checked={chosen.includes(sc)}
                                        onCheckedChange={(on) => setScopes(on ? [...chosen, sc] : chosen.filter((x) => x !== sc))}
                                    />
                                </li>
                            ))}
                        </ul>
                    </section>
                    <FormField label="Expires after (minutes)" htmlFor="session-ttl" hint="1 minute to 24 hours.">
                        <Input id="session-ttl" inputMode="numeric" className={cn(INPUT, 'w-32 tabular-nums')} value={minutes} onChange={(e) => setMinutes(e.target.value)} />
                    </FormField>
                    {error && <p className="m-0 text-[12px] text-red-600 dark:text-red-400">{error}</p>}
                </div>
            </ConsoleDialog>
            <RevealOnceSecret
                secret={session?.token ?? null}
                title="Test session"
                description="This is the only time you'll see this token. In production, mint sessions on your server."
                onDone={done}
            >
                {(token) => (
                    <div className="flex flex-col gap-2">
                        <CodeSnippet code={token} />
                        {session?.expiresAt && <SessionCountdown expiresAt={session.expiresAt} />}
                    </div>
                )}
            </RevealOnceSecret>
        </>
    );
}

function SessionCountdown({ expiresAt }: { expiresAt: Date }) {
    const { now } = useConsole();
    const [, tick] = useState(0);
    useEffect(() => {
        const t = window.setInterval(() => tick((n) => n + 1), 1000);
        return () => window.clearInterval(t);
    }, []);
    const left = expiresAt.getTime() - now();
    return (
        <p className="m-0 text-[12px] tabular-nums text-muted-foreground">
            {left > 0 ? `Expires in ${formatDuration(Math.floor(left / 1000) * 1000)}` : 'Expired'} · <TimeCell value={expiresAt} tier="absolute" />
        </p>
    );
}

function SuspendUserDialog({ user, open, onOpenChange, onSuspend }: { user: User; open: boolean; onOpenChange: (open: boolean) => void; onSuspend: () => Promise<boolean> }) {
    const [busy, setBusy] = useState(false);
    const confirm = async () => {
        setBusy(true);
        const done = await onSuspend();
        setBusy(false);
        if (done) onOpenChange(false);
    };
    return (
        <ConsoleDialog
            open={open}
            onOpenChange={onOpenChange}
            size="sm"
            title={`Suspend ${user.id}?`}
            description="Every call made for them is refused until you reactivate them, including their sessions. Their inboxes and phone numbers keep receiving, so delete those too if they must go quiet. Their history stays readable."
            footer={
                <>
                    <ConsoleButton variant="ghost" onClick={() => onOpenChange(false)}>
                        Cancel
                    </ConsoleButton>
                    <ConsoleButton variant="danger" onClick={confirm} disabled={busy}>
                        Suspend
                    </ConsoleButton>
                </>
            }
        />
    );
}

/** What a paused user is told, how long ago, and what waits to run. */
function SpendingPausedNotice({ user, onResume, busy }: { user: User; onResume: () => void; busy: boolean }) {
    const spending = user.spending!;
    return (
        <section aria-label="Spending paused" className={cn('mb-8 flex flex-col gap-2.5 rounded-lg border bg-foreground/[0.03] px-3.5 py-3 text-[13px]', HAIRLINE)}>
            <p className="m-0 text-muted-foreground">
                Spending paused <TimeCell value={spending.since} />
                {spending.pausedBy === 'console' ? ' from the console' : ''}. Nothing that costs money runs for them until you resume them.{' '}
                {spending.held ? `${plural(spending.held, 'message')} they sent will run when you do.` : 'Nothing they sent is waiting.'}
            </p>
            <figure className="m-0 flex flex-col gap-1.5 border-l-2 border-foreground/15 pl-3">
                <figcaption className="text-[12px] font-medium text-muted-foreground">What they&apos;re told</figcaption>
                <blockquote className="m-0 text-foreground/90">{spending.message}</blockquote>
                {spending.action && (
                    <a href={spending.action.url} target="_blank" rel="noopener noreferrer" className="w-fit text-[13px] font-medium text-foreground underline underline-offset-2">
                        {spending.action.label}
                    </a>
                )}
            </figure>
            <div>
                <ConsoleButton size="sm" variant="soft" onClick={onResume} disabled={busy}>
                    Resume spending
                </ConsoleButton>
            </div>
        </section>
    );
}

/** Pause what a user can spend, in your words, with your page to pay on. */
function PauseSpendingDialog({ user, open, onOpenChange, onPaused }: { user: User; open: boolean; onOpenChange: (open: boolean) => void; onPaused: (u: User) => void }) {
    const fallback = useAccount().data?.spending_paused ?? null;
    const [message, setMessage] = useState('');
    const [label, setLabel] = useState('');
    const [url, setUrl] = useState('');
    const [error, setError] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);
    useEffect(() => {
        if (!open) return;
        setMessage('');
        setLabel('');
        setUrl('');
        setError(null);
    }, [open]);
    const pause = async () => {
        if (!message.trim() && !fallback?.message) return setError('Say what they can do, or set a default under Settings, Paused spending.');
        if (!label.trim() !== !url.trim()) return setError('A button needs both a label and a link.');
        setBusy(true);
        try {
            const action = label.trim() ? { label: label.trim(), url: url.trim() } : undefined;
            onPaused(await user.pauseSpending({ message: message.trim() || undefined, action }));
            toast.success(`${user.id}'s spending paused`);
            onOpenChange(false);
        } catch (e) {
            setError(formError(e).message);
        } finally {
            setBusy(false);
        }
    };
    return (
        <ConsoleDialog
            open={open}
            onOpenChange={onOpenChange}
            size="sm"
            title={`Pause ${user.id}'s spending?`}
            description="Nothing that costs money runs for them until you resume. Messages they send an agent get your message back and wait to run; what they already have keeps running and billing."
            footer={
                <>
                    <ConsoleButton variant="ghost" onClick={() => onOpenChange(false)}>
                        Cancel
                    </ConsoleButton>
                    <ConsoleButton variant="primary" onClick={() => void pause()} disabled={busy}>
                        Pause spending
                    </ConsoleButton>
                </>
            }
        >
            <form
                className="flex flex-col gap-3"
                onSubmit={(e) => {
                    e.preventDefault();
                    void pause();
                }}
            >
                <FormField
                    label="What they're told"
                    htmlFor="pause-message"
                    error={error}
                    hint={fallback?.message ? 'Blank uses your default from Settings.' : 'A call reads it aloud, so keep links in the button.'}
                >
                    <Textarea id="pause-message" rows={3} maxLength={500} className="text-[13px] md:text-[13px]" placeholder={fallback?.message ?? "You've used this month's credits."} value={message} onChange={(e) => setMessage(e.target.value)} />
                </FormField>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
                    <FormField label="Button" htmlFor="pause-label">
                        <Input id="pause-label" maxLength={40} className={INPUT} placeholder={fallback?.action?.label ?? 'Top up'} value={label} onChange={(e) => setLabel(e.target.value)} />
                    </FormField>
                    <FormField label="Link" htmlFor="pause-url" hint="Your checkout or billing page; {{user.id}} fills in their id.">
                        <Input id="pause-url" inputMode="url" className={cn(INPUT, 'font-mono')} placeholder={fallback?.action?.url ?? 'https://'} value={url} onChange={(e) => setUrl(e.target.value)} />
                    </FormField>
                </div>
            </form>
        </ConsoleDialog>
    );
}

function DeleteUserDialog({ user, open, onOpenChange }: { user: User; open: boolean; onOpenChange: (open: boolean) => void }) {
    const { lab } = useConsole();
    const href = useConsoleHref();
    const navigate = useNavigate();
    const [typed, setTyped] = useState('');
    const [error, setError] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);
    const reportHeld = useReportHeld(useConsole());
    const remove = async () => {
        setBusy(true);
        try {
            await user.delete();
            invalidateV1('users');
            toast.success(`${user.id} deleted`);
            onOpenChange(false);
            navigate(href('users'));
        } catch (e) {
            // Held for the account's owner: the dialog's done, and a toast follows it until it's done or not.
            if (reportHeld(e, `Delete ${user.id}`, () => invalidateV1('users'))) onOpenChange(false);
            else setError(formError(e).message);
        } finally {
            setBusy(false);
        }
    };
    return (
        <ConsoleDialog
            open={open}
            onOpenChange={(o) => {
                if (!o) setTyped('');
                onOpenChange(o);
            }}
            size="sm"
            title={`Delete ${user.id}?`}
            description="Their calls stop and they leave the user list. Runs and usage they made stay in your history."
            footer={
                <>
                    <ConsoleButton variant="ghost" onClick={() => onOpenChange(false)}>
                        Cancel
                    </ConsoleButton>
                    <ConsoleButton variant="danger" onClick={remove} disabled={busy || typed !== user.id}>
                        Delete user
                    </ConsoleButton>
                </>
            }
        >
            {lab && (
                <div className="mb-3 flex flex-col gap-1.5 text-[13px] text-muted-foreground">
                    <p className="m-0">Nothing acts for them afterwards:</p>
                    <ul aria-label="What deleting stops" className="m-0 flex list-disc flex-col gap-0.5 pl-5">
                        <li>their connections&apos; grants are revoked at each provider;</li>
                        <li>their agents&apos; schedules, webhooks, app events and queues stop waking them;</li>
                        <li>their inboxes stop receiving mail, and their phone numbers are released.</li>
                    </ul>
                    <p className="m-0">Their operations, tool calls, conversations, usage and spend stay readable, and the data their databases, buckets, repos and volumes hold stays until you delete it.</p>
                </div>
            )}
            <FormField label={`Type ${user.id} to confirm`} htmlFor="delete-user-confirm" error={error}>
                <Input id="delete-user-confirm" className={cn(INPUT, 'font-mono')} value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" />
            </FormField>
        </ConsoleDialog>
    );
}

// ── the page ───────────────────────────────────────────────────────────────

export default function UserDetail({ rest }: ConsolePageProps) {
    const id = rest[0];
    const { client } = useConsole();
    const href = useConsoleHref();
    const user = useV1(`users/${id}`, () => User.get(id, { client }));
    const [dialog, setDialog] = useState<'suspend' | 'session' | 'delete' | 'pause' | null>(null);
    const [resuming, setResuming] = useState(false);
    const u = user.data;

    useEffect(() => {
        if (u) recordRecent({ type: 'user', id: u.id, label: u.id, path: userPath(u.id) });
    }, [u]);

    const crumbs = [{ label: 'Users', href: href('users') }];
    if (!u) {
        return (
            <>
                <PageHeader crumbs={crumbs} title={id} />
                {user.error !== undefined ? <ErrorPanel error={user.error} onRetry={user.refresh} /> : <div aria-busy className="h-48 animate-pulse rounded-xl bg-foreground/[0.04]" />}
            </>
        );
    }

    const suspended = u.status === 'suspended';
    const saved = (next: User) => user.mutate(next);
    const resume = async () => {
        const held = u.spending?.held ?? 0;
        setResuming(true);
        try {
            saved(await u.resumeSpending());
            toast.success(held ? `${u.id} can spend again; ${plural(held, 'waiting message')} run now` : `${u.id} can spend again`);
        } catch (e) {
            toast.error(formError(e).message);
        } finally {
            setResuming(false);
        }
    };
    const spendingPaused = u.spending?.paused === true;
    const connectBlocked = suspended ? SUSPENDED_REASON : null;
    /** True once the status changed; a refusal shows as a toast. */
    const setStatus = async (status: 'active' | 'suspended'): Promise<boolean> => {
        try {
            saved(await (status === 'suspended' ? u.suspend() : u.reactivate()));
            await user.refresh();
            invalidateV1('users');
            toast.success(status === 'suspended' ? `${u.id} suspended` : `${u.id} reactivated`);
            return true;
        } catch (e) {
            toast.error(formError(e).message);
            return false;
        }
    };

    return (
        <>
            <PageHeader
                crumbs={crumbs}
                title={u.id}
                purpose={[u.name, u.email].filter(Boolean).join(' · ') || undefined}
                chips={suspended ? <StatusPill look={userStatusLook(u.status)} /> : undefined}
                actions={
                    <>
                        {connectBlocked && (
                            <span id="connect-blocked" className="max-w-[16rem] text-right text-[12px] text-muted-foreground">
                                {connectBlocked}
                            </span>
                        )}
                        <NewInCode kind="connection" place={{ user: u.id }} disabled={!!connectBlocked} aria-describedby={connectBlocked ? 'connect-blocked' : undefined} />
                        <MoreMenu
                            label="User actions"
                            items={[
                                suspended ? { label: 'Reactivate', onSelect: () => void setStatus('active') } : { label: 'Suspend', onSelect: () => setDialog('suspend') },
                                { label: 'Test session', onSelect: () => setDialog('session'), disabled: suspended, reason: SUSPENDED_REASON },
                                { label: 'Delete', danger: true, separated: true, onSelect: () => setDialog('delete') },
                            ]}
                        />
                    </>
                }
            />
            {suspended && (
                <p role="status" className={cn('mb-8 rounded-lg border bg-foreground/[0.03] px-3 py-2 text-[13px] text-muted-foreground', HAIRLINE)}>
                    Suspended. Calls made for them are refused until you reactivate them; their history stays readable.
                </p>
            )}
            {spendingPaused && !suspended && <SpendingPausedNotice user={u} onResume={() => void resume()} busy={resuming} />}
            <DetailLayout
                main={
                    <>
                        <Now user={u} />
                        <PageSection title="Connections" note="Their named accounts. Your code and their agents act in them by name; NoClick keeps the tokens fresh.">
                            <ConnectionsTable
                                userFilter={u.id}
                                blocked={suspended ? SUSPENDED_REASON : null}
                                empty={`No connections yet. Create one and send ${u.id} its link, or let an agent ask for one.`}
                            />
                        </PageSection>
                        <PageSection title="Recent runs">
                            <OperationsView pinned={`user:${u.id}`} controls={false} limit={6} viewAllHref={href('logs', { q: `user:${u.id}` })} />
                        </PageSection>
                        <PageSection title="Code" note="Act for this user from your code: every call inside uses their connections and counts toward their cap.">
                            <CodeSnippet tabs={snippetTabs(userCodeSnippet(u.id))} />
                        </PageSection>
                    </>
                }
                aside={
                    <>
                        <About user={u} onSaved={saved} spending={{ onPause: () => setDialog('pause'), onResume: () => void resume() }} />
                        <Uses user={u} />
                    </>
                }
            />
            <SuspendUserDialog user={u} open={dialog === 'suspend'} onOpenChange={(o) => setDialog(o ? 'suspend' : null)} onSuspend={() => setStatus('suspended')} />
            <MintSessionDialog user={u} open={dialog === 'session'} onOpenChange={(o) => setDialog(o ? 'session' : null)} />
            <DeleteUserDialog user={u} open={dialog === 'delete'} onOpenChange={(o) => setDialog(o ? 'delete' : null)} />
            <PauseSpendingDialog user={u} open={dialog === 'pause'} onOpenChange={(o) => setDialog(o ? 'pause' : null)} onPaused={saved} />
        </>
    );
}
