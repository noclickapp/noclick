// What a provider said when asked about one account, on its page: its own things as it sees them (your channels,
// your repositories), who it signs in as, or its refusal in its own words. A check that didn't go through says
// nothing about the account, and says so.
import type { ReactNode } from 'react';
import { ChevronRight, Loader2 } from 'lucide-react';
import { checkVerdict, type ConnectionCheck } from '@/lib/connectionCheck';
import { Surface } from '@/screens/resources/ui';
import { BUTTON_PRIMARY } from '@/ui/buttons';
import { cn } from '@/ui/utils';

/** Asking the provider about an account: under way, its answer, or the asking itself failed (a rate limit, a dropped
 *  connection), which says nothing about the account. */
export type ConnectionProbe = { status: 'checking' } | { status: 'done'; result: ConnectionCheck } | { status: 'failed'; error: string };

function Dot({ tone }: { tone: 'ok' | 'bad' | 'quiet' }) {
    return (
        <span
            aria-hidden
            className={cn('h-2 w-2 shrink-0 rounded-full', tone === 'ok' ? 'bg-emerald-500' : tone === 'bad' ? 'bg-red-500' : 'bg-muted-foreground/50')}
        />
    );
}

function ProofShell({ tone, title, children, className }: { tone: 'ok' | 'bad' | 'quiet'; title: string; children?: ReactNode; className?: string }) {
    return (
        <Surface className={cn('px-4 py-4 sm:px-5', className)}>
            <p className="flex items-center gap-2.5 text-[14px] font-medium text-foreground">
                <Dot tone={tone} />
                {title}
            </p>
            {children}
        </Surface>
    );
}

/** What `provider` said when asked about this account. `canCheck` is false where NoClick can't ask it on its own;
 *  `onReconnect` offers Reconnect beside a refusal. */
export function Proof({ provider, probe, canCheck, onReconnect }: { provider: string; probe?: ConnectionProbe; canCheck: boolean; onReconnect?: () => void }) {
    if (!canCheck) {
        return <p className="text-[14px] leading-relaxed text-muted-foreground">NoClick can’t ask {provider} about this account on its own. Each run that uses it checks it.</p>;
    }
    if (!probe || probe.status === 'checking') {
        return (
            <Surface className="flex items-center gap-2.5 px-4 py-4 text-[14px] text-muted-foreground sm:px-5">
                <Loader2 className="h-4 w-4 animate-spin" />
                Asking {provider}…
            </Surface>
        );
    }
    if (probe.status === 'failed') {
        return (
            <ProofShell tone="quiet" title="Couldn’t check just now">
                <p className="mt-1.5 text-[13.5px] leading-relaxed text-muted-foreground">The check itself didn’t go through, so this says nothing about the account. Try again in a minute.</p>
            </ProofShell>
        );
    }
    const result = probe.result;
    const state = checkVerdict(result);
    if (state === 'rejected') {
        return (
            <ProofShell tone="bad" title={`${provider} turned it down`} className="border-red-500/25 dark:border-red-500/25">
                {result.hint ? (
                    <>
                        <p className="mt-1.5 text-[13.5px] leading-relaxed text-muted-foreground">{result.hint}</p>
                        {result.error && (
                            <details className="group mt-2.5">
                                <summary className="inline-flex cursor-pointer list-none items-center gap-1 text-[12.5px] text-muted-foreground transition-colors hover:text-foreground [&::-webkit-details-marker]:hidden">
                                    <ChevronRight className="h-3.5 w-3.5 transition-transform group-open:rotate-90" />
                                    {provider}’s reply
                                </summary>
                                <p className="mt-2 break-words font-mono text-[12px] leading-relaxed text-red-600 dark:text-red-400">{result.error}</p>
                            </details>
                        )}
                    </>
                ) : (
                    result.error && <p className="mt-2 break-words font-mono text-[12px] leading-relaxed text-red-600 dark:text-red-400">{result.error}</p>
                )}
                {onReconnect && (
                    <button type="button" onClick={onReconnect} className={cn(BUTTON_PRIMARY, 'mt-4')}>
                        Reconnect
                    </button>
                )}
            </ProofShell>
        );
    }
    if (state === 'unverified') {
        return (
            <ProofShell tone="quiet" title="No clear answer">
                <p className="mt-1.5 text-[13.5px] leading-relaxed text-muted-foreground">{provider} didn’t confirm or refuse it just now. Automations still use it, and the next run will tell.</p>
            </ProofShell>
        );
    }
    const samples = result.samples ?? [];
    const more = result.total && result.total > samples.length ? result.total - samples.length : 0;
    return (
        <ProofShell tone="ok" title="Working">
            {samples.length > 0 ? (
                <>
                    <p className="mt-3 text-[12.5px] text-muted-foreground">Your {result.noun ?? 'items'}, as {provider} sees them</p>
                    <div className="mt-2 flex flex-wrap gap-1.5" data-testid="connection-evidence">
                        {samples.map((sample) => (
                            <span key={sample.value ?? sample.label} className="inline-flex h-7 max-w-full items-center truncate rounded-full bg-secondary px-3 text-[13px] text-foreground dark:bg-foreground/[0.07]">
                                {sample.label}
                            </span>
                        ))}
                        {more > 0 && <span className="inline-flex h-7 items-center px-1.5 text-[13px] text-muted-foreground">+{more} more</span>}
                    </div>
                    {result.account_label && <p className="mt-3 text-[12.5px] text-muted-foreground">Signed in as {result.account_label}</p>}
                </>
            ) : (
                <p className="mt-1.5 text-[13.5px] leading-relaxed text-muted-foreground">
                    {result.proves === 'reachability'
                        ? `${provider} accepted it. It has nothing account-specific to show.`
                        : result.account_label
                          ? `Signed in as ${result.account_label}.`
                          : `${provider} answered.`}
                </p>
            )}
        </ProofShell>
    );
}
