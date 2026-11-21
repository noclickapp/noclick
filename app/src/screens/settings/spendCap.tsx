// Settings → Plan and billing's monthly spending cap: what the account spent this period against it, and the way to
// set, raise, lower or remove it. Reaching it stops new work that costs money until the period resets. Whoever draws it
// hands in the cap as it read it and how a change is saved (`SpendCapControl`). One of the account's keys only lowers
// it, or sets one where there's none (`lowerOnly`): raising or removing it is the owner's, on NoClick
// (screens/console/ownerOnly.ts, `accountCap`).
import { useState, type FormEvent, type ReactNode } from 'react';
import { ExternalLink, Gauge, Loader2 } from 'lucide-react';
import { formatFunds } from '@/lib/formatters';
import { money } from '@/screens/usage/derive';
import { BUTTON_GHOST, BUTTON_PRIMARY, BUTTON_SECONDARY } from '@/ui/buttons';
import { FIELD, FIELD_LABEL, QUIET_LINK } from '@/ui/fields';
import { ShellDialog } from '@/ui/ShellDialog';
import { cn } from '@/ui/utils';
import { SettingsRow } from './parts';

export const MIN_CAP_USD = 1;
export const MAX_CAP_USD = 1_000_000;

export interface SpendCapState {
    /** Whole dollars a billing period; null where none is set. */
    capUsd: number | null;
    /** Charged so far this period, as Settings → Usage totals it. */
    spentUsd: number;
    periodStart: string;
    resetsAt: string;
    reached: boolean;
    /** Whether this person pays, and so sets it; else who does. */
    payer: { self: true } | { self: false; name: string };
}

/** The cap as its reader read it, and how a change is saved. */
export interface SpendCapControl {
    state: SpendCapState | null;
    loadError: string | null;
    saving: boolean;
    error: string | null;
    setError: (error: string | null) => void;
    /** Whole dollars, or null to remove it. True once saved. */
    save: (capUsd: number | null) => Promise<boolean>;
    refresh: () => Promise<void>;
}

/** Where someone who may only lower the cap (one of the account's keys) raises or removes it: NoClick's own page. */
export interface LowerOnly {
    raiseAt: string;
}

const dollars = (usd: number) => formatFunds(usd);
const day = (iso: string) => new Date(iso).toLocaleDateString('en-US', { month: 'long', day: 'numeric', timeZone: 'UTC' });

/** The draft as a cap the rules allow, or why not. */
export function checkCap(draft: string): { capUsd: number } | { error: string } {
    const capUsd = Number(draft);
    if (!draft.trim() || !Number.isInteger(capUsd) || capUsd < MIN_CAP_USD || capUsd > MAX_CAP_USD) {
        return { error: `Enter whole dollars from ${dollars(MIN_CAP_USD)} to ${dollars(MAX_CAP_USD)}.` };
    }
    return { capUsd };
}

function Meter({ state }: { state: SpendCapState }) {
    const share = state.capUsd ? Math.min(1, state.spentUsd / state.capUsd) : 0;
    return (
        <div
            role="meter"
            aria-label="Spent this period"
            aria-valuemin={0}
            aria-valuemax={state.capUsd ?? 0}
            aria-valuenow={Math.min(state.spentUsd, state.capUsd ?? 0)}
            className="mt-2.5 h-1.5 w-full max-w-[320px] overflow-hidden rounded-full bg-foreground/[0.08]"
        >
            <div
                className={cn('h-full rounded-full transition-[width] duration-500', state.reached ? 'bg-red-600 dark:bg-red-400' : 'bg-foreground/70')}
                style={{ width: `${share * 100}%` }}
            />
        </div>
    );
}

function Description({ state }: { state: SpendCapState }) {
    const spent = money(state.spentUsd);
    const of = state.capUsd !== null ? `${spent} of ${dollars(state.capUsd)} spent this period` : null;
    if (!state.payer.self) {
        return (
            <>
                <span>
                    {of ? `${of}. ` : 'No cap. '}Set by {state.payer.name}, who pays for this workspace’s work.
                </span>
                {state.capUsd !== null && <Meter state={state} />}
            </>
        );
    }
    if (state.capUsd === null) return <span>No cap. {spent} spent this period.</span>;
    if (state.reached) {
        return (
            <>
                <span className="text-red-600 dark:text-red-400">
                    You’ve hit your {dollars(state.capUsd)} monthly cap ({spent} spent). Work that costs money waits until it resets on {day(state.resetsAt)}.
                </span>
                <Meter state={state} />
            </>
        );
    }
    return (
        <>
            <span>
                {of} · resets {day(state.resetsAt)}
            </span>
            <Meter state={state} />
        </>
    );
}

/** NoClick's own page, for what this reader can't do here. */
function OnNoClick({ href, className, children }: { href: string; className: string; children: ReactNode }) {
    return (
        <a href={href} target="_blank" rel="noreferrer" className={className}>
            {children}
            <ExternalLink aria-hidden className="h-3.5 w-3.5" />
        </a>
    );
}

export function SpendCapRow({ cap, lowerOnly = null }: { cap: SpendCapControl; lowerOnly?: LowerOnly | null }) {
    const [editing, setEditing] = useState(false);
    const [draft, setDraft] = useState('');
    const s = cap.state;

    const label = 'Monthly spending cap';
    if (!s) {
        return (
            <SettingsRow
                label={label}
                description={
                    cap.loadError ? (
                        <span role="alert">
                            {cap.loadError}{' '}
                            <button type="button" className={QUIET_LINK} onClick={() => void cap.refresh()}>
                                Try again
                            </button>
                        </span>
                    ) : (
                        <span aria-label="Loading the spending cap" className="inline-block h-3.5 w-48 animate-pulse rounded bg-foreground/[0.06] align-middle" />
                    )
                }
            />
        );
    }

    const open = () => {
        setDraft(s.capUsd !== null ? String(s.capUsd) : '');
        cap.setError(null);
        setEditing(true);
    };
    const checked = checkCap(draft);
    // Above the cap in place: only its owner raises it.
    const raises = lowerOnly !== null && 'capUsd' in checked && s.capUsd !== null && checked.capUsd > s.capUsd;
    const submit = async (e: FormEvent) => {
        e.preventDefault();
        if ('error' in checked || raises) return;
        if (await cap.save(checked.capUsd)) setEditing(false);
    };
    const remove = async () => {
        if (await cap.save(null)) setEditing(false);
    };

    let control: ReactNode = null;
    if (s.payer.self && lowerOnly && s.reached) {
        control = (
            <OnNoClick href={lowerOnly.raiseAt} className={BUTTON_PRIMARY}>
                Raise it on NoClick
            </OnNoClick>
        );
    } else if (s.payer.self) {
        control = (
            <button type="button" onClick={open} className={s.reached ? BUTTON_PRIMARY : BUTTON_SECONDARY}>
                {s.capUsd === null ? 'Set a cap' : s.reached ? 'Raise cap' : 'Change'}
            </button>
        );
    }
    const atOrUnder = 'capUsd' in checked && checked.capUsd <= s.spentUsd;

    return (
        <div data-testid="spend-cap-section">
            <SettingsRow label={label} description={<Description state={s} />} control={control} />
            <ShellDialog
                open={editing}
                onOpenChange={(next) => !cap.saving && setEditing(next)}
                title={label}
                mark={<Gauge className="h-5 w-5" strokeWidth={1.75} />}
                description={
                    lowerOnly
                        ? 'Once this period’s spending reaches it, work that costs money stops until the period resets or the account’s owner raises it.'
                        : 'Once this period’s spending reaches it, work that costs money stops until the period resets or you raise it.'
                }
                onSubmit={submit}
                footer={
                    <>
                        {s.capUsd !== null && !lowerOnly && (
                            <button type="button" onClick={() => void remove()} disabled={cap.saving} className={cn(BUTTON_GHOST, 'sm:mr-auto')}>
                                Remove cap
                            </button>
                        )}
                        <button type="button" onClick={() => setEditing(false)} disabled={cap.saving} className={BUTTON_GHOST}>
                            Cancel
                        </button>
                        <button type="submit" disabled={'error' in checked || raises || cap.saving} className={BUTTON_PRIMARY}>
                            {cap.saving && <Loader2 className="h-4 w-4 animate-spin" />}
                            Save
                        </button>
                    </>
                }
            >
                <div className="space-y-3 pt-2">
                    <div>
                        <label htmlFor="spend-cap-usd" className={FIELD_LABEL}>
                            Cap each period
                        </label>
                        <div className="relative max-w-[220px]">
                            <span className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-[14px] text-muted-foreground">$</span>
                            <input
                                id="spend-cap-usd"
                                inputMode="numeric"
                                value={draft}
                                disabled={cap.saving}
                                placeholder="100"
                                onChange={(e) => setDraft(e.target.value.replace(/[^0-9]/g, ''))}
                                className={cn(FIELD, 'pl-7 tabular-nums')}
                            />
                        </div>
                    </div>
                    {draft && 'error' in checked ? (
                        <p className="text-[12.5px] text-red-600 dark:text-red-400" role="alert">
                            {checked.error}
                        </p>
                    ) : raises && lowerOnly ? (
                        <p className="text-[12.5px] text-red-600 dark:text-red-400" role="alert">
                            This app lowers the cap, or sets one where there’s none. The account’s owner raises it on NoClick.
                        </p>
                    ) : atOrUnder ? (
                        <p className="text-[12.5px] leading-relaxed text-foreground/85" role="status">
                            That’s at or under the {money(s.spentUsd)} already spent this period, so work that costs money stops as soon as you save.
                        </p>
                    ) : null}
                    <p className="text-[12.5px] leading-relaxed text-muted-foreground">
                        {money(s.spentUsd)} spent so far this period, which resets on {day(s.resetsAt)}. What you already have, like numbers and domains, keeps renewing, and published sites keep serving up to twice the cap.
                    </p>
                    {lowerOnly && s.capUsd !== null && (
                        <OnNoClick href={lowerOnly.raiseAt} className={cn(QUIET_LINK, 'inline-flex items-center gap-1 text-[12.5px]')}>
                            Raise or remove it on NoClick
                        </OnNoClick>
                    )}
                    {cap.error && (
                        <p className="text-[13px] text-red-600 dark:text-red-400" role="alert">
                            {cap.error}
                        </p>
                    )}
                </div>
            </ShellDialog>
        </div>
    );
}
