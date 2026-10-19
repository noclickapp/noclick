// The one renderer for "did this credential actually work?" — fed by the
// connect-time verification a create/update returns and by the on-demand
// credential:test_connection probe, so the connect dialog, the node panel, the
// Setup step and the public provide page all tell the same three stories:
//
//   working     the provider answered with THIS account's data (their
//               workbooks, their channels) — the proof leads, the account name
//               supports; a probe that only proves reachability says so;
//   rejected    the provider refused — its own words, then what that usually
//               means, then a way back into the form;
//   unverified  nothing could be judged (no probe declared, a timeout) — said
//               plainly, never dressed up as green.
//
// No box: a mark (green only for proof, red only for a refusal) and the story in the surface's own type.
import type { ReactNode } from 'react';
import { AlertTriangle, Check, CheckCircle2, MinusCircle, RotateCw } from 'lucide-react';
import type { CredentialTestConnectionResponse } from '~/types/socket-events.generated';
import { cn } from '~/lib/utils';

export type ConnectionVerdictState = 'working' | 'rejected' | 'unverified';

export function verdictState(
    verification: CredentialTestConnectionResponse | null | undefined,
): ConnectionVerdictState {
    if (verification?.reachable === true) return 'working';
    if (verification?.reachable === false) return 'rejected';
    return 'unverified';
}

/** One-line summary of a working verdict — the picker's "connected as" line. */
export function verdictSummary(
    verification: CredentialTestConnectionResponse | null | undefined,
): string | null {
    if (!verification || verification.reachable !== true) return null;
    const samples = (verification.samples ?? []).map((s) => s.label);
    if (samples.length) {
        const more = verification.total && verification.total > samples.length
            ? ` +${verification.total - samples.length} more`
            : '';
        return `${verification.noun ?? 'items'}: ${samples.join(', ')}${more}`;
    }
    if (verification.account_label) return verification.account_label;
    return verification.proves === 'reachability' ? 'key accepted' : 'connected';
}

const TONE: Record<ConnectionVerdictState, string> = {
    working: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400',
    rejected: 'bg-red-500/10 text-red-600 dark:text-red-400',
    unverified: 'bg-foreground/[0.06] text-muted-foreground',
};
const MARK = { working: Check, rejected: AlertTriangle, unverified: MinusCircle } as const;

export function ConnectionVerdict({
    verification,
    providerLabel,
    onReconnect,
    reconnectLabel,
    onPick,
    picked,
    pickField,
    accountLine,
    className,
}: {
    verification: CredentialTestConnectionResponse | null | undefined;
    /** "Tableau", "Slack" — names who rejected or accepted. */
    providerLabel: string;
    /** Rejected state's way back into the form. */
    onReconnect?: () => void;
    reconnectLabel?: string;
    /** When the samples can fill a config field (answers_field matches
        pickField), each sample becomes a choice. */
    onPick?: (value: string) => void;
    picked?: string;
    pickField?: string | null;
    /** Who the account is, when the probe named nobody (a sign-in's email). */
    accountLine?: string;
    className?: string;
}) {
    const state = verdictState(verification);
    const live = verification?.samples ?? [];
    const samples = live.map((s) => s.label);
    const more = verification?.total && verification.total > samples.length ? verification.total - samples.length : 0;
    const account = verification?.account_label ?? accountLine;
    const canPick = Boolean(onPick && pickField && verification?.answers_field === pickField);
    const Mark = MARK[state];

    let lead: string;
    let detail: ReactNode = null;
    if (state === 'working') {
        if (samples.length) {
            lead = `Your ${verification?.noun ?? 'items'}${canPick ? ': pick one' : ''}`;
            detail = canPick ? (
                <span className="mt-1.5 flex flex-wrap gap-1.5">
                    {live.map((s) => (
                        <button
                            key={s.value ?? s.label}
                            type="button"
                            onClick={() => onPick?.(s.value ?? s.label)}
                            aria-pressed={picked === (s.value ?? s.label)}
                            className={cn(
                                'inline-flex h-7 items-center rounded-full px-3 text-[12.5px] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                                picked === (s.value ?? s.label)
                                    ? 'bg-primary font-medium text-primary-foreground'
                                    : 'bg-secondary text-foreground hover:bg-accent dark:bg-foreground/[0.07] dark:hover:bg-foreground/[0.11]'
                            )}
                        >
                            {s.label}
                        </button>
                    ))}
                    {more ? <span className="self-center text-[12.5px]">and {more} more</span> : null}
                </span>
            ) : (
                <>
                    <span className="text-foreground/90">{samples.join(', ')}</span>
                    {more ? ` and ${more} more` : ''}
                </>
            );
        } else if (verification?.proves === 'reachability') {
            lead = `${providerLabel} accepted this key`;
            detail = 'There’s nothing account-specific to show, but it answered.';
        } else {
            lead = account ? `Connected as ${account}` : `${providerLabel} answered`;
        }
    } else if (state === 'rejected') {
        lead = `${providerLabel} turned it down`;
        detail = (
            <>
                {verification?.error && <span className="block break-words font-mono text-[12px] text-foreground/80">{verification.error}</span>}
                {verification?.hint && <span className="mt-1 block">{verification.hint}</span>}
            </>
        );
    } else {
        lead = 'Saved, not verified';
        detail = `${providerLabel} couldn’t be asked to confirm it just now. The first run will tell.`;
    }

    return (
        <div className={cn('flex items-start gap-3.5', className)} data-testid="connection-verdict" data-state={state}>
            <span className={cn('grid h-9 w-9 shrink-0 place-items-center rounded-full', TONE[state])}>
                <Mark className="h-[18px] w-[18px]" strokeWidth={2.25} />
            </span>
            <div className="min-w-0 flex-1 pt-1.5">
                <p className="m-0 text-[14.5px] font-medium leading-snug text-foreground">{lead}</p>
                {detail && <div className="mb-0 mt-1 text-[13px] leading-relaxed text-muted-foreground">{detail}</div>}
                {state === 'working' && samples.length > 0 && account && <p className="mb-0 mt-1 text-[13px] text-muted-foreground">{account}</p>}
                {state === 'rejected' && onReconnect && (
                    <button type="button" onClick={onReconnect} className="mt-3 inline-flex h-9 items-center gap-1.5 rounded-full bg-primary px-4 text-[13.5px] font-medium text-primary-foreground transition-opacity hover:opacity-90">
                        <RotateCw className="h-3.5 w-3.5" /> {reconnectLabel ?? `Reconnect ${providerLabel}`}
                    </button>
                )}
            </div>
        </div>
    );
}

/** What a credential's row remembers its connect-time check proved, as one line: who it is ("Verified as
 *  dhruv@acme.co"), else one of the things it reached, else the sign-in's email; null when it was never verified. */
export function storedVerdictLine(metadata: Record<string, unknown> | undefined): string | null {
    const { verified_as: who, verified_with: reached, email } = metadata ?? {};
    if (typeof who === 'string' && who) return `Verified as ${who}`;
    if (typeof reached === 'string' && reached) return `Verified, it can see ${reached}`;
    return typeof email === 'string' && email ? email : null;
}

/** That line under an account picker, for an account connected before this session. */
export function StoredVerdict({ metadata, className }: { metadata: Record<string, unknown> | undefined; className?: string }) {
    const line = storedVerdictLine(metadata);
    if (!line) return null;
    return (
        <p className={cn('flex items-center gap-1.5 text-[12.5px] text-muted-foreground', className)} data-testid="credential-verified-as">
            <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
            {line}
        </p>
    );
}
