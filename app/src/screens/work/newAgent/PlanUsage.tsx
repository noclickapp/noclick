// A Claude or ChatGPT plan's usage in Work's account pill and its menu: the reading for the pick's model (GET
// /v1/connections/{ref}/usage, kept or fresh), re-read on its connection's `plan_usage` frame and never polled, and the
// bars that fill as a window is used, in ink alone (a window near its limit reads in full ink; red stays for failures).
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

/** One window: its name and how much is used, a bar that fills as it's used, and when it resets (or comes back). */
export function UsageWindow({
    w,
    now,
    reset = true,
}: {
    w: PlanWindow;
    now: Date;
    reset?: boolean;
}) {
    const tight = windowTight(w);
    const when = reset ? windowReset(w, now) : null;
    const fill =
        w.state === 'used_up' ? 100 : Math.max(0, Math.min(100, w.used * 100));
    return (
        <span className="block" data-testid="plan-window" data-state={w.state}>
            <span className="flex items-baseline justify-between gap-2 text-[12px] leading-[18px] max-sm:text-[13px]">
                <span className="truncate text-foreground/80">{w.label}</span>
                <span
                    className={cn(
                        'shrink-0 whitespace-nowrap tabular-nums',
                        tight
                            ? 'font-medium text-foreground'
                            : 'text-muted-foreground'
                    )}
                >
                    {windowUse(w)}
                </span>
            </span>
            <span
                aria-hidden
                className="mt-[5px] block h-1 overflow-hidden rounded-full bg-foreground/[0.08]"
            >
                <span
                    className={cn(
                        'block h-full rounded-full transition-[width] duration-700',
                        tight ? 'bg-foreground' : 'bg-muted-foreground'
                    )}
                    style={{ width: `${fill}%` }}
                />
            </span>
            {when && (
                <span className="mt-1 block text-[11.5px] tabular-nums text-muted-foreground max-sm:text-[12.5px]">
                    {when}
                </span>
            )}
        </span>
    );
}

/** A plan's windows, one bar each, as the menu shows them under the account that's used. */
export function UsageWindows({ windows }: { windows: readonly PlanWindow[] }) {
    const now = useNow();
    if (!windows.length) return null;
    return (
        <span className="mt-2 flex flex-col gap-2.5" data-testid="plan-usage">
            {windows.map((w) => (
                <UsageWindow key={`${w.kind}:${w.label}`} w={w} now={now} />
            ))}
        </span>
    );
}
