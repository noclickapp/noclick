// The usage page's data: one read (`usage:page`), and again when something changes it. A charge recorded for this
// tab's work and credits running out arrive as frames; anything else (another tab's runs, a trigger's, funds landing
// after checkout) is caught when the page comes back into view, and every minute while it stays open.
import { useCallback, useEffect, useRef, useState } from 'react';
import { socketCall } from '~/lib/socketCall';
import { onSocketEvent } from '~/lib/socket-receiver';
import { toSnapshot } from '~/components/usage/page/derive';
import type { ChargesPage, ChargesSource, UsagePageData, UsageSnapshot } from '~/components/usage/page/types';

const BACKSTOP_MS = 60_000;
// A busy run records a charge every few seconds; one re-read covers a burst.
const SETTLE_MS = 5_000;

export interface UsagePageState {
    snap: UsageSnapshot | null;
    firstPage: ChargesPage | null;
    error: string | null;
    reload: () => void;
    charges: ChargesSource;
}

/** What the page showed when it was last open in this tab: a return shows it at once and reads it again. It's the
 *  socket's account's, and a tab viewing another account starts over (a reload). */
let kept: { snap: UsageSnapshot; firstPage: ChargesPage; period: UsagePageData['period'] } | null = null;

/** Forget it, as a new tab would (a test's next page). */
export function forgetUsagePage(): void {
    kept = null;
}

export function useUsagePage(): UsagePageState {
    const [data, setData] = useState<{ snap: UsageSnapshot; firstPage: ChargesPage } | null>(() => kept);
    const [error, setError] = useState<string | null>(null);
    const inFlight = useRef(false);
    const period = useRef<UsagePageData['period'] | null>(kept?.period ?? null);

    const load = useCallback(async () => {
        if (inFlight.current) return;
        inFlight.current = true;
        try {
            const page = (await socketCall('usage:page')) as unknown as UsagePageData;
            period.current = page.period;
            kept = { snap: toSnapshot(page), firstPage: page.charges, period: page.period };
            setData(kept);
            setError(null);
        } catch (e) {
            setError(e instanceof Error ? e.message : 'Usage didn’t load');
        } finally {
            inFlight.current = false;
        }
    }, []);

    useEffect(() => {
        void load();
        let settle: ReturnType<typeof setTimeout> | null = null;
        const soon = () => {
            if (settle) return;
            settle = setTimeout(() => {
                settle = null;
                void load();
            }, SETTLE_MS);
        };
        const visible = () => document.visibilityState === 'visible';
        const onVisible = () => visible() && void load();
        const backstop = setInterval(() => visible() && void load(), BACKSTOP_MS);
        const offUsage = onSocketEvent('usage:event', soon);
        const offExhausted = onSocketEvent('credits:exhausted', () => void load());
        document.addEventListener('visibilitychange', onVisible);
        window.addEventListener('focus', onVisible);
        return () => {
            if (settle) clearTimeout(settle);
            clearInterval(backstop);
            offUsage();
            offExhausted();
            document.removeEventListener('visibilitychange', onVisible);
            window.removeEventListener('focus', onVisible);
        };
    }, [load]);

    const charges = useCallback<ChargesSource>(async (query, cursor, limit) => {
        const p = period.current;
        if (!p) return { rows: [], runs: {}, next: null };
        return (await socketCall('usage:charges', {
            start: p.window_start,
            end: p.window_end,
            keys: query.keys ?? undefined,
            day: query.day ?? undefined,
            cursor: cursor ?? undefined,
            limit,
        })) as unknown as ChargesPage;
    }, []);

    return { snap: data?.snap ?? null, firstPage: data?.firstPage ?? null, error, reload: load, charges };
}
