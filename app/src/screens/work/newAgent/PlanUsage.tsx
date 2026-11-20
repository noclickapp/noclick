// A Claude or ChatGPT plan's usage in Work's account pill and its menu: the reading for the pick's model (GET
// /v1/connections/{ref}/usage, kept or fresh), re-read on its connection's `plan_usage` frame and never polled, and the
// meter and line each plan shows: what's left of the window that stops it first, and how much is used and when it
// resets (near its limit in full ink; used up, red, since the plan has stopped).
import { useEffect, useState } from 'react';
import {
    Connection,
    type PlanUsage,
    type PlanWindow,
} from 'noclick';
import { cn } from '@/ui/utils';
import { useWorkV1 } from '../agents/reads';
import { useWorkFrames } from '@/sdk/live';
import { isPlanAccount, type ModelAccount } from './accounts';
import { windowReset, windowTight, windowUse } from './planWords';


/** The plan's usage for `model` (the windows that can stop it), while `enabled`: NoClick's last reading, or with
 *  `fresh` the provider's where that one is a few minutes old. Re-read when the plan's connection says its usage moved. */
export function usePlanUsage(
    account: ModelAccount | null | undefined,
    model: string,
    options: { fresh?: boolean; enabled?: boolean } = {}
) {
    const fresh = options.fresh ?? false;
    const on =
        (options.enabled ?? true) &&
        !!account &&
        isPlanAccount(account) &&
        account.connected &&
        !account.plan?.refusal;
    const ref = account?.id ?? '';
    const read = useWorkV1<PlanUsage>(
        on
            ? `work:plan-usage:${fresh ? 'fresh' : 'kept'}:${ref}:${model}`
            : null,
        (client) =>
            Connection.fromId(ref, { client }).usage({
                model: model || undefined,
                fresh,
            })
    );
    useWorkFrames('platform:resource', (frame) => {
        if (
            on &&
            frame.kind === 'plan_usage' &&
            (frame.id === account?.connectionId || frame.id === ref)
        )
            void read.refresh();
    });
    return read;
}

/** The time now, again every `everyMs` while mounted: a reset's countdown stays true while it's shown. */
export function useNow(everyMs = 30_000): Date {
    const [now, setNow] = useState(() => new Date());
    useEffect(() => {
        const timer = window.setInterval(() => setNow(new Date()), everyMs);
        return () => window.clearInterval(timer);
    }, [everyMs]);
    return now;
}

/** A plan's meter beside its name: a short bar of what's left of the window that stops it first, like a battery, in
 *  ink while there's room, full ink near its limit, and an empty red track once it's used up. Its title names every
 *  window that can stop the pick. */
export function UsageMeter({ w, title }: { w: PlanWindow; title: string }) {
    const out = w.state === 'used_up';
    const left = out ? 0 : Math.max(0, Math.min(100, (1 - w.used) * 100));
    return (
        <span title={title} data-testid="plan-meter" data-state={w.state} className="grid shrink-0 place-items-center py-1.5">
            <span aria-hidden className={cn('block h-1 w-[22px] overflow-hidden rounded-full transition-colors', out ? 'bg-red-600/45 dark:bg-red-400/55' : 'bg-foreground/[0.12]')}>
                <span className={cn('block h-full rounded-full transition-[width] duration-700 motion-reduce:transition-none', windowTight(w) ? 'bg-foreground' : 'bg-muted-foreground')} style={{ width: `${left}%` }} />
            </span>
        </span>
    );
}

/** The line under a plan: how much of the window that stops it first is used and when it resets ("41% used ·
 *  resets Mon 4:13 PM", "Used up · back in 2 h 54 min"), in full ink near its limit, "Used up" in red. */
export function UsageLine({ w, now }: { w: PlanWindow; now: Date }) {
    const reset = windowReset(w, now);
    return (
        <span data-testid="plan-usage" data-state={w.state} className={cn('block text-[11.5px] leading-snug tabular-nums max-sm:text-[12.5px]', windowTight(w) ? 'text-foreground' : 'text-muted-foreground')}>
            <span className={w.state === 'used_up' ? 'text-red-600 dark:text-red-400' : undefined}>{windowUse(w)}</span>
            {reset && ` · ${reset}`}
        </span>
    );
}
