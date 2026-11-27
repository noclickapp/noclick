// What failed, grouped by why, with its fix: atop Logs' runs, one line per cause (`Operation.failures()`: one cap used
// up or one connection disconnected fails every run behind it the same way) saying what happened, how many, since
// when and what it touched, beside "See the runs" (the list's `cause:` filter) and the one button that fixes it; and
// atop a failed run, the same words and fix with the runs stopped the same way. The words are lib/failures.ts, the fix
// the console's one rule (lib/failureFix.ts); the button here does it in place where it can (a cap raised, a user's
// spending resumed, a connection's link made), else opens where it's done.
import { useRef, useState } from 'react';
import { Link } from 'react-router';
import { ArrowUpRight, Check } from 'lucide-react';
import { toast } from 'sonner';
import { HAIRLINE } from '@/ui/primitives';
import { Input } from '@/ui/input';
import { cn } from '@/ui/utils';
import { ALL_USERS, Agent, Connection, Operation, Project, User, type OperationFailure } from 'noclick';
import { updateKey } from '@/sdk/owner';
import { useReportHeld } from '@/sdk/held';
import { invalidateV1, useV1 } from '@/sdk/useV1';
import type { FailureFix, FixPlace, InPlaceFix } from '@/screens/console/lib/failureFix';
import { failureWords, touched } from '@/screens/console/lib/failures';
import { formatMoney } from '@/screens/console/lib/format';
import { useConsole, useConsoleHref } from '@/screens/console/hooks/useConsole';
import { useSearchParam } from '@/screens/console/hooks/useQueryState';
import { useOwnerOnly } from '../ownerOnly';
import { ConsoleButton, consoleButtonClass } from '../ui/Button';
import { capLabel } from '../ui/CapMeter';
import { ConsoleDialog } from '../ui/ConsoleDialog';
import { TimeCell } from '../ui/TimeCell';
import { ConnectLinkDialog } from '../connections';
import { useConsoleNames } from './OperationDrawer';
import { FormField, INPUT, formError, parseUsd } from './Users';

/** Where a fix links, and the names the console has read for agents and keys. */
export function useFixPlace(): FixPlace {
    const { site } = useConsole();
    const href = useConsoleHref();
    const names = useConsoleNames();
    return { href, site, agentName: (id) => names.agent(id)?.name ?? null, keyName: (id) => names.key(id)?.name ?? null };
}

/** After a fix: what the failures' reads, and the reads of the thing fixed, show again. */
function fixed(prefix: string) {
    invalidateV1('operations/failures');
    invalidateV1(prefix);
}

// ── the fixes ─────────────────────────────────────────────────────────────

/** Raise a user's or key's cap, or an agent's or app's budget, where the failure says it was used up. */
function RaiseCapDialog({ fix, label, onClose, onDone }: { fix: Extract<InPlaceFix, { kind: 'cap' }>; label: string; onClose: () => void; onDone: (cap: number | null) => void }) {
    const { client } = useConsole();
    const reportHeld = useReportHeld(useConsole());
    const [draft, setDraft] = useState(fix.cap === null ? '' : String(fix.cap * 2));
    const [error, setError] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);
    const save = async () => {
        const parsed = parseUsd(draft);
        if (parsed.error) return setError(parsed.error);
        setBusy(true);
        setError(null);
        try {
            const value = parsed.value;
            if (fix.scope === 'user') await User.fromId(fix.id, { client }).update({ spendCapUsdPerMonth: value });
            else if (fix.scope === 'key') await updateKey(client, fix.id, { spend_cap_usd_per_month: value });
            // Loaded first: an agent of a user is changed as that user, which the read across users resolves.
            else if (fix.scope === 'agent') await (await Agent.get(fix.id, { client, user: null })).update({ budgetUsdPerMonth: value });
            else await (await Project.get(fix.id, { client })).update({ budgetUsdPerMonth: value });
            fixed(fix.scope === 'project' ? 'projects' : `${fix.scope}s`);
            toast.success(value === null ? `${fix.who} has no ${fix.noun} now` : `${fix.who}’s ${fix.noun} is ${capLabel(value)} a month now`);
            onDone(value);
        } catch (e) {
            if (reportHeld(e, label)) return onClose();
            setError(formError(e).message);
        } finally {
            setBusy(false);
        }
    };
    return (
        <ConsoleDialog
            open
            onOpenChange={(o) => !o && onClose()}
            title={label}
            description={
                fix.cap === null
                    ? `What ${fix.who} may spend each month.`
                    : `${fix.who} has spent ${fix.spent === null ? 'all' : formatMoney(fix.spent)} of its ${capLabel(fix.cap)} ${fix.noun} this month. Runs it stopped don’t start again on their own.`
            }
            onSubmit={(e) => {
                e.preventDefault();
                void save();
            }}
            footer={
                <>
                    <ConsoleButton variant="ghost" onClick={onClose}>
                        Cancel
                    </ConsoleButton>
                    <ConsoleButton variant="primary" type="submit" disabled={busy}>
                        {busy ? 'Saving…' : 'Save'}
                    </ConsoleButton>
                </>
            }
        >
            <FormField label={`Monthly ${fix.noun} (USD)`} htmlFor="failure-cap" error={error} hint={`Leave it empty for no ${fix.noun}.`}>
                <Input id="failure-cap" inputMode="decimal" autoFocus className={cn(INPUT, 'tabular-nums')} value={draft} onChange={(e) => setDraft(e.target.value)} />
            </FormField>
        </ConsoleDialog>
    );
}

/** The connection a failure names, loaded to make it a new connect link (as the user whose runs it stopped). */
function ReconnectDialog({ connection, label, user, onClose }: { connection: string; label: string; user: string | null; onClose: () => void }) {
    const { client } = useConsole();
    const found = useV1(`connections/${connection}?failure&${user ?? ''}`, () => Connection.get(connection, { client, user }));
    if (found.error !== undefined) {
        return <ConsoleDialog open onOpenChange={(o) => !o && onClose()} title={label} description={formError(found.error).message} footer={<ConsoleButton onClick={onClose}>Close</ConsoleButton>} />;
    }
    return found.data ? <ConnectLinkDialog connection={found.data} onClose={onClose} /> : null;
}

/** A fix in place: the button, its dialog, and once it's done, what it did. */
function InPlace({ fix, label, user, look, doneLook }: { fix: InPlaceFix; label: string; user: string | null; look: string; doneLook: string }) {
    const { client } = useConsole();
    const reportHeld = useReportHeld(useConsole());
    const [open, setOpen] = useState(false);
    const [busy, setBusy] = useState(false);
    const [done, setDone] = useState<string | null>(null);
    if (done) {
        return (
            <span className={cn(doneLook, 'pointer-events-none')}>
                <Check className="h-3.5 w-3.5" aria-hidden />
                {done}
            </span>
        );
    }
    if (fix.kind === 'resume') {
        const resume = async () => {
            setBusy(true);
            try {
                await User.fromId(fix.userId, { client }).resumeSpending();
                fixed('users');
                toast.success(`${fix.userId}’s spending is resumed`);
                setDone('Resumed');
            } catch (e) {
                if (!reportHeld(e, label)) toast.error(formError(e).message);
            } finally {
                setBusy(false);
            }
        };
        return (
            <button type="button" className={look} disabled={busy} onClick={() => void resume()}>
                {busy ? 'Resuming…' : label}
            </button>
        );
    }
    return (
        <>
            <button type="button" className={look} onClick={() => setOpen(true)}>
                {label}
            </button>
            {open && fix.kind === 'cap' && (
                <RaiseCapDialog
                    fix={fix}
                    label={label}
                    onClose={() => setOpen(false)}
                    onDone={(cap) => {
                        setOpen(false);
                        setDone(cap === null ? `No ${fix.noun} now` : `Raised to ${capLabel(cap)}`);
                    }}
                />
            )}
            {open && fix.kind === 'reconnect' && <ReconnectDialog connection={fix.connection} label={label} user={user} onClose={() => setOpen(false)} />}
        </>
    );
}

/**
 * The one button that fixes a failure: in place where it can (a key's cap only as the owner, who alone changes keys),
 * else a link to where it's done. `user` is whose runs it stopped, when one user's.
 */
export function FixButton({ fix, user = null, size = 'sm', className }: { fix: FailureFix; user?: string | null; size?: 'sm' | 'md'; className?: string }) {
    const ownerCan = useOwnerOnly();
    const look = consoleButtonClass('primary', size, className);
    const inPlace = fix.inPlace && !(fix.inPlace.kind === 'cap' && fix.inPlace.scope === 'key' && !ownerCan('keys')) ? fix.inPlace : null;
    if (inPlace) return <InPlace fix={inPlace} label={fix.label} user={user} look={look} doneLook={consoleButtonClass('ghost', size, className)} />;
    if (fix.external) {
        return (
            <a href={fix.href} target="_blank" rel="noopener noreferrer" className={look}>
                {fix.label}
                <ArrowUpRight className="h-3.5 w-3.5" aria-hidden />
            </a>
        );
    }
    return (
        <Link to={fix.href} className={look}>
            {fix.label}
        </Link>
    );
}

// ── on Logs ────────────────────────────────────────────────────────────────

export interface FailureWindow {
    /** What the read covers: the page's own filters (user, agent, key, kind) and time. */
    options: Record<string, unknown>;
    /** "Failed in the last day". */
    title: string;
    /** Changes when a run newly failed, so the causes are read again. */
    version: string;
}

function FailureRow({ failure, place, selected, onSee }: { failure: OperationFailure; place: FixPlace; selected: boolean; onSee: (cause: string | null) => void }) {
    const words = failureWords(failure.error, failure.failedOn, failure.count, place);
    const who = touched(failure, place);
    const user = failure.userCount === 1 ? failure.userIds[0] : null;
    return (
        <li className={cn('flex flex-col gap-2 border-t px-4 py-3 first:border-t-0 sm:flex-row sm:items-center sm:gap-4', HAIRLINE)}>
            <span aria-hidden className="mt-1.5 hidden h-[7px] w-[7px] shrink-0 self-start rounded-full bg-red-500 sm:block" />
            <div className="min-w-0 flex-1">
                <p className="m-0 text-[14px] font-medium text-foreground">{words.what}</p>
                <p className="m-0 text-[13px] text-muted-foreground">
                    {words.detail && <>{words.detail.replace(/\.$/, '')} · </>}
                    {who && <span className="text-foreground/70">{who} · </span>}
                    {failure.count > 1 ? (
                        <>
                            first <TimeCell value={failure.firstAt} />, last <TimeCell value={failure.lastAt} />
                        </>
                    ) : (
                        <TimeCell value={failure.lastAt} />
                    )}
                </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
                <ConsoleButton size="sm" aria-pressed={selected} onClick={() => onSee(selected ? null : failure.cause)}>
                    {selected ? 'Show every run' : failure.count === 1 ? 'See the run' : `See the ${failure.count} runs`}
                </ConsoleButton>
                {words.fix && <FixButton fix={words.fix} user={user} />}
            </div>
        </li>
    );
}

/** "Failed in the last day": each cause of the runs that failed in the page's window, newest first. Nothing when none
 *  did. `selected` is the cause the list shows (its `cause:` token); `onSee` shows one, or every run again. */
export function FailureGroups({ window: w, selected, onSee }: { window: FailureWindow; selected: string | null; onSee: (cause: string | null) => void }) {
    const { client } = useConsole();
    const place = useFixPlace();
    const key = `operations/failures?${JSON.stringify(w.options)}&${w.version}`;
    const read = useV1(key, () => Operation.failures({ client, ...w.options, limit: 20 }));
    // Read again for a new window or a new failure, the causes shown stay until the new ones land.
    const last = useRef(read.data);
    if (read.data) last.current = read.data;
    const shown = read.data ?? last.current;
    if (read.error !== undefined) {
        return (
            <p className="m-0 text-[13px] text-muted-foreground">
                Couldn&apos;t read what failed.{' '}
                <button type="button" className="font-medium text-foreground hover:underline" onClick={() => void read.refresh()}>
                    Try again
                </button>
            </p>
        );
    }
    if (!shown?.causes.length) return null;
    return (
        <section aria-label={w.title} className="flex flex-col gap-2">
            <h2 className="m-0 text-[15px] font-semibold tracking-[-0.01em] text-foreground">
                {w.title} <span className="ml-1 font-normal tabular-nums text-muted-foreground">{shown.total}</span>
            </h2>
            <ul className="m-0 list-none rounded-xl bg-red-500/[0.05] p-0 dark:bg-red-500/[0.07]">
                {shown.causes.map((f) => (
                    <FailureRow key={f.cause} failure={f} place={place} selected={selected === f.cause} onSee={onSee} />
                ))}
            </ul>
            {shown.hasMore && <p className="m-0 text-[12px] text-muted-foreground">Other causes failed too: narrow the time or the user to see them.</p>}
        </section>
    );
}

// ── atop a failed run ──────────────────────────────────────────────────────

/** A failed run, fix first: what happened, its fix, and the other runs stopped the same way. */
export function FailedRun({ op }: { op: Operation }) {
    const { client } = useConsole();
    const place = useFixPlace();
    const [, setOp] = useSearchParam('op');
    const cause = op.cause;
    const others = useV1(cause ? `operations?failure=${cause}` : null, () => Operation.listPage({ client, cause: cause!, status: 'failed', userFilter: ALL_USERS, limit: 4 }));
    const words = failureWords(op.error, op.failedOn, null, place);
    const also = (others.data?.data ?? []).filter((o) => o.id !== op.id).slice(0, 3);
    return (
        <section aria-label="Why it failed" className="flex flex-col gap-3">
            <div className="flex flex-col gap-3 rounded-xl bg-red-500/[0.05] p-4 dark:bg-red-500/[0.07]">
                <div>
                    <p className="m-0 text-[14px] font-medium text-foreground">{words.what}</p>
                    {words.detail && <p className="m-0 mt-0.5 text-[13px] text-muted-foreground">{words.detail}</p>}
                </div>
                {words.fix && <FixButton fix={words.fix} user={op.userId} size="md" className="self-start" />}
            </div>
            {also.length > 0 && (
                <div>
                    <p className="m-0 mb-1 text-[12px] font-medium text-muted-foreground">Also stopped this way</p>
                    <ul className="m-0 list-none p-0">
                        {also.map((o) => (
                            <li key={o.id}>
                                <button type="button" onClick={() => setOp(o.id, { push: true })} className="flex w-full items-baseline gap-2 py-1 text-left text-[13px] text-foreground hover:underline">
                                    <span className="min-w-0 truncate">{o.summaryText || o.kind}</span>
                                    <TimeCell value={o.createdAt} className="shrink-0 text-muted-foreground" />
                                </button>
                            </li>
                        ))}
                    </ul>
                </div>
            )}
        </section>
    );
}
