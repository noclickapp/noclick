// The one renderer for "did this credential actually work?" — fed by the
// connect-time verification a create/update returns and by the on-demand
// credential:test_connection probe, so the node panel, the Setup step and the
// public provide page all tell the same three stories:
//
//   working     the provider answered with THIS account's data (their
//               workbooks, their channels) — the proof leads, the account name
//               supports; a probe that only proves reachability says so;
//   rejected    the provider refused — its own words, then what that usually
//               means, then a way back into the form;
//   unverified  nothing could be judged (no probe declared, a timeout) — said
//               plainly, never dressed up as green.
import { AlertTriangle, Check, MinusCircle, RotateCw } from 'lucide-react';
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
    /** Supporting line when the probe named no account. */
    accountLine?: string;
    className?: string;
}) {
    const state = verdictState(verification);

    if (state === 'working') {
        const live = verification?.samples ?? [];
        const samples = live.map((s) => s.label);
        const canPick = Boolean(onPick && pickField && verification?.answers_field === pickField);
        const more = verification?.total && verification.total > samples.length
            ? verification.total - samples.length
            : 0;
        const reachabilityOnly = verification?.proves === 'reachability';
        return (
            <div className={cn('rounded-lg border border-emerald-500/25 bg-emerald-500/[0.06] px-3.5 py-3', className)}>
                <div className="flex gap-2.5">
                    <Check className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
                    <div className="min-w-0">
                        {samples.length > 0 ? (
                            <>
                                <p className="m-0 text-[13.5px] leading-relaxed">
                                    <span className="text-foreground/55">
                                        Your {verification?.noun ?? 'items'}
                                        {canPick ? ' — pick one' : ''}:{' '}
                                    </span>
                                    {canPick ? (
                                        <span className="inline-flex flex-wrap gap-1.5 align-middle">
                                            {live.map((s) => (
                                                <button
                                                    key={s.value ?? s.label}
                                                    type="button"
                                                    onClick={() => onPick?.(s.value ?? s.label)}
                                                    className={cn(
                                                        'rounded-md border px-2 py-0.5 text-[12.5px] transition-colors',
                                                        picked === (s.value ?? s.label)
                                                            ? 'border-emerald-500/50 bg-emerald-500/15 font-medium text-foreground'
                                                            : 'border-foreground/15 text-foreground/80 hover:border-foreground/35 hover:bg-foreground/5',
                                                    )}
                                                >
                                                    {s.label}
                                                </button>
                                            ))}
                                        </span>
                                    ) : (
                                        <span className="font-medium text-foreground/95">{samples.join(', ')}</span>
                                    )}
                                    {more ? <span className="text-foreground/40"> +{more} more</span> : null}
                                </p>
                                {(verification?.account_label || accountLine) && (
                                    <p className="mb-0 mt-1 text-[12px] text-foreground/40">
                                        {verification?.account_label ?? accountLine}
                                    </p>
                                )}
                            </>
                        ) : (
                            <>
                                <p className="m-0 text-[13.5px] font-medium">
                                    {reachabilityOnly
                                        ? `${providerLabel} accepted this key`
                                        : verification?.account_label
                                            ? `Connected as ${verification.account_label}`
                                            : 'Working'}
                                </p>
                                <p className="mb-0 mt-0.5 text-[12.5px] leading-relaxed text-foreground/55">
                                    {reachabilityOnly
                                        ? 'Nothing account-specific to show, but the provider answered.'
                                        : verification?.account_label
                                            ? `${providerLabel} answered; the account has no ${verification?.noun ?? 'items'} to show yet.`
                                            : (accountLine ?? `${providerLabel} answered.`)}
                                </p>
                            </>
                        )}
                    </div>
                </div>
            </div>
        );
    }

    if (state === 'rejected') {
        return (
            <div className={cn('rounded-lg border border-red-500/25 bg-red-500/[0.06] px-3.5 py-3', className)}>
                <div className="flex gap-2.5">
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-red-600 dark:text-red-400" />
                    <div className="min-w-0">
                        <p className="m-0 text-[13.5px] font-medium">{providerLabel} rejected this credential</p>
                        {verification?.error && (
                            <p className="mb-0 mt-2 break-words font-mono text-[11.5px] text-red-600/80 dark:text-red-400/80">
                                {verification.error}
                            </p>
                        )}
                        {verification?.hint && (
                            <p className="mb-0 mt-1.5 text-[12.5px] leading-relaxed text-foreground/60">
                                {verification.hint}
                            </p>
                        )}
                        {onReconnect && (
                            <button
                                type="button"
                                onClick={onReconnect}
                                className="mt-2.5 inline-flex items-center gap-2 rounded-lg bg-primary px-3.5 py-1.5 text-[12.5px] font-medium text-primary-foreground transition-opacity hover:opacity-90"
                            >
                                <RotateCw className="h-3 w-3" /> {reconnectLabel ?? `Reconnect ${providerLabel}`}
                            </button>
                        )}
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div className={cn('rounded-lg border border-border bg-foreground/[0.03] px-3.5 py-3', className)}>
            <div className="flex gap-2.5">
                <MinusCircle className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                <div className="min-w-0">
                    <p className="m-0 text-[13.5px] font-medium">Saved, not verified</p>
                    <p className="mb-0 mt-0.5 text-[12.5px] leading-relaxed text-foreground/55">
                        {`${providerLabel} couldn't be asked to confirm it just now. The first run will tell.`}
                    </p>
                </div>
            </div>
        </div>
    );
}
