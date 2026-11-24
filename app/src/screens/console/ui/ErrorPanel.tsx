import { HAIRLINE } from '@/ui/primitives';
import { cn } from '@/ui/utils';
import { useContext } from 'react';
import { NoClickError } from 'noclick';
import { ConsoleContext } from '@/screens/console/hooks/useConsole';
import { heldCallOf } from '@/sdk/held';
import { invalidateV1 } from '@/sdk/useV1';
import { HeldCallNotice } from '@/ui/HeldCallNotice';
import { ConsoleButton } from './Button';

/**
 * The API's message and next_step, verbatim. A `not_available` (a vendor this
 * deployment doesn't hold, or something that can't be done now) is a state,
 * not a failure: it reads in ink, not red. A call held for the account's owner
 * is a state too, followed until it's done (src/sdk/held.ts).
 */
export function ErrorPanel({ error, onRetry, className }: { error: unknown; onRetry?: () => void; className?: string }) {
    // Held for the account's owner: nothing failed, it waits on them, and what it changes is read again once it's done.
    const held = heldCallOf(error);
    const from = useContext(ConsoleContext);
    if (held) return <HeldCallNotice held={held} what={held.summary ?? 'This'} from={from} onSettled={(state) => state.phase === 'done' && invalidateV1('')} className={className} />;
    const api = error instanceof NoClickError ? error : null;
    const unavailable = api?.type === 'not_available';
    const message = error instanceof Error ? error.message : String(error);
    return (
        <div role={unavailable ? 'status' : 'alert'} className={cn('rounded-xl border bg-card p-4', HAIRLINE, className)}>
            <p className={cn('m-0 text-sm font-medium', unavailable ? 'text-foreground' : 'text-red-600 dark:text-red-400')}>{message}</p>
            {api?.nextStep && <p className="m-0 mt-1 text-sm text-muted-foreground">{api.nextStep}</p>}
            <div className="mt-3 flex items-center gap-3">
                {onRetry && (
                    <ConsoleButton size="sm" onClick={onRetry}>
                        Retry
                    </ConsoleButton>
                )}
                {api?.requestId && <span className="font-mono text-[12px] text-muted-foreground">request {api.requestId}</span>}
            </div>
        </div>
    );
}
