import { HAIRLINE } from '@/ui/primitives';
import { cn } from '@/ui/utils';
import { NoClickError } from 'noclick';
import { ConsoleButton } from './Button';

/**
 * The API's message and next_step, verbatim. A `not_available` (a vendor this
 * deployment doesn't hold, or something that can't be done now) is a state,
 * not a failure: it reads in ink, not red.
 */
export function ErrorPanel({ error, onRetry, className }: { error: unknown; onRetry?: () => void; className?: string }) {
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
