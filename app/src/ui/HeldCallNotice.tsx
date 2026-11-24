// A call NoClick holds for the account's owner, said where the screen made it (src/sdk/held.ts): sent to them to
// approve and where, then approved and running, then done or not done and why. A notice, never an error: nothing
// failed, it waits on a person.
import { CheckCircle2, Clock, Loader2, XCircle } from 'lucide-react';
import { heldLines, settled, useHeldCall, type HeldCall, type HeldSource, type HeldState, type HeldWords } from '@/sdk/held';
import { NOTICE, NOTICE_MARK, NOTICE_TEXT, NOTICE_TITLE } from '@/ui/notices';
import { cn } from '@/ui/utils';

/** `held`, followed while shown; `onSettled` hears where it ended (done: read what it changed again). */
export function HeldCallNotice({
    held,
    onSettled,
    from,
    className,
    ...words
}: HeldWords & { held: HeldCall; onSettled?: (state: HeldState) => void; /** Where it was made; the page's client and frames by default. */ from?: HeldSource | null; className?: string }) {
    const state = useHeldCall(held, onSettled, from);
    const { title, text } = heldLines(held, state, words);
    const phase = state?.phase ?? 'waiting';
    const Mark = phase === 'done' ? CheckCircle2 : phase === 'running' ? Loader2 : settled(state) ? XCircle : Clock;
    return (
        <div role="status" data-testid="held-call" data-phase={phase} className={cn(NOTICE, 'flex items-start gap-2.5 px-3.5 py-3 text-[13.5px] leading-snug', className)}>
            <Mark
                className={cn(
                    'mt-[1px] h-4 w-4 shrink-0',
                    phase === 'running' && 'animate-spin',
                    phase === 'done' ? 'text-emerald-600 dark:text-emerald-400' : settled(state) ? 'text-red-600 dark:text-red-400' : NOTICE_MARK
                )}
                strokeWidth={1.75}
            />
            <div className="min-w-0">
                <p className={cn('font-medium', NOTICE_TITLE)}>{title}</p>
                {text && <p className={cn('mt-0.5', NOTICE_TEXT)}>{text}</p>}
            </div>
        </div>
    );
}
