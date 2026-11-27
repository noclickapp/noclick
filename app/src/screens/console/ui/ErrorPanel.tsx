import { HAIRLINE } from '@/ui/primitives';
import { cn } from '@/ui/utils';
import { useContext } from 'react';
import { ArrowUpRight } from 'lucide-react';
import { Link } from 'react-router';
import { NoClickError } from 'noclick';
import { ConsoleContext, consoleHref } from '@/screens/console/hooks/useConsole';
import { failureFix } from '@/screens/console/lib/failureFix';
import { heldCallOf } from '@/sdk/held';
import { invalidateV1 } from '@/sdk/useV1';
import { HeldCallNotice } from '@/ui/HeldCallNotice';
import { ConsoleButton, consoleButtonClass } from './Button';
import { CopyButton } from './CopyButton';

/**
 * A failure as a person reads it: what happened in the API's own words and its next step, then the one button that
 * fixes it where the console knows it (raise the cap that was reached, reconnect the account, add funds) beside Retry,
 * and only after those, folded, the error's type, its request id and a copy of it as JSON. A `not_available` (a vendor
 * this deployment doesn't hold, or something that can't be done now) is a state, not a failure: it reads in ink, not
 * red. A call held for the account's owner is a state too, followed until it's done (src/sdk/held.ts).
 */
export function ErrorPanel({ error, onRetry, className }: { error: unknown; onRetry?: () => void; className?: string }) {
    // Held for the account's owner: nothing failed, it waits on them, and what it changes is read again once it's done.
    const held = heldCallOf(error);
    const from = useContext(ConsoleContext);
    if (held) return <HeldCallNotice held={held} what={held.summary ?? 'This'} from={from} onSettled={(state) => state.phase === 'done' && invalidateV1('')} className={className} />;
    const api = error instanceof NoClickError ? error : null;
    const unavailable = api?.type === 'not_available';
    const message = error instanceof Error ? error.message : String(error);
    const fix = from ? failureFix(error, { href: (path, params) => consoleHref(from.basePath, path, params), site: from.site }) : null;
    return (
        <div role={unavailable ? 'status' : 'alert'} className={cn('rounded-xl border bg-card p-4', HAIRLINE, className)}>
            <p className={cn('m-0 text-sm font-medium', unavailable ? 'text-foreground' : 'text-red-600 dark:text-red-400')}>{message}</p>
            {api?.nextStep && <p className="m-0 mt-1 text-sm text-muted-foreground">{api.nextStep}</p>}
            {(fix || onRetry) && (
                <div className="mt-3 flex flex-wrap items-center gap-2">
                    {fix &&
                        (fix.external ? (
                            <a href={fix.href} target="_blank" rel="noopener noreferrer" className={consoleButtonClass('primary', 'sm')}>
                                {fix.label} <ArrowUpRight aria-hidden className="h-3.5 w-3.5" />
                            </a>
                        ) : (
                            <Link to={fix.href} className={consoleButtonClass('primary', 'sm')}>
                                {fix.label}
                            </Link>
                        ))}
                    {onRetry && (
                        <ConsoleButton size="sm" onClick={onRetry}>
                            Retry
                        </ConsoleButton>
                    )}
                </div>
            )}
            {api && (
                <details className="mt-3 text-[12px] text-muted-foreground">
                    <summary className="cursor-pointer select-none">Details</summary>
                    <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono">
                        <span>{api.type}</span>
                        {api.status !== null && <span>{api.status}</span>}
                        {api.requestId && <span>request {api.requestId}</span>}
                        <span className="inline-flex items-center gap-0.5 font-sans">
                            Copy as JSON <CopyButton value={JSON.stringify(api.toJSON(), null, 2)} label="Copy the error as JSON" />
                        </span>
                    </div>
                </details>
            )}
        </div>
    );
}
