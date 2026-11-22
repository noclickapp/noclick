// The usage page's data, read through the SDK client its host hands it: the account's ledger (`Usage.ledger`), the
// money behind it (`Usage.billing`) and its first page of charges (`Usage.charges`), together. They're read again when
// the host's live frames say the account was charged (`platform:usage`, one a burst), that a workstream was renamed or
// archived (whose name its charges read under), or that anything may have moved (`reset`), and when the page comes back
// into view: never on a timer. The read is kept per client (useV1), so a return
// to the page shows it at once and reads it again behind it.
import { useCallback, useRef } from 'react';
import { Usage, type NoClick, type UsageCharges } from 'noclick';
import { useClient } from '@/sdk/client';
import { useWorkFrames } from '@/sdk/live';
import { invalidateV1, useV1 } from '@/sdk/useV1';
import { ZONE, toSnapshot } from './derive';
import type { ChargesPage, ChargesSource, UsageBilling, UsagePageData, UsageSnapshot } from './types';

/** The read's key in the client's cache: everything drawn from it (the page, a host's preview) shares it. */
export const USAGE_READ = 'usage:page';

export interface UsagePageState {
    snap: UsageSnapshot | null;
    firstPage: ChargesPage | null;
    error: string | null;
    reload: () => void;
    charges: ChargesSource;
}

interface UsageRead {
    snap: UsageSnapshot;
    firstPage: ChargesPage;
    period: UsagePageData['period'];
}

const NO_CHARGES: ChargesPage = { rows: [], runs: {}, next: null };

/** A page of charges as the table draws it. */
function pageOf(answer: UsageCharges): ChargesPage {
    const { rows, runs, next } = answer.raw as unknown as ChargesPage;
    return { rows, runs, next };
}

/** The page's read: the ledger with its days in the reader's zone, the money behind it, and the billing period's first
 *  page of charges, all at once. */
async function readUsage(client: NoClick): Promise<UsageRead> {
    const [ledger, billing, first] = await Promise.all([Usage.ledger({ client, tz: ZONE }), Usage.billing({ client }), Usage.charges({ client })]);
    const { now, account, period, groups, directory } = ledger.raw as unknown as Omit<UsagePageData, 'billing' | 'charges'>;
    const firstPage = pageOf(first);
    const page: UsagePageData = { now, account, period, groups, directory, billing: (billing?.raw ?? null) as UsageBilling | null, charges: firstPage };
    return { snap: toSnapshot(page), firstPage, period };
}

/** Reads the usage page again wherever it's drawn: what a host calls when it hears the account was charged its own way. */
export function readUsageAgain(): void {
    invalidateV1(USAGE_READ);
}

/** The page's read, with the client a `ClientProvider` above gives and the frames a `WorkLiveContext` above delivers. */
export function useUsagePage(): UsagePageState {
    const client = useClient();
    const { data, error, refresh } = useV1(USAGE_READ, () => readUsage(client), { client });
    useWorkFrames('platform:usage', readUsageAgain);
    useWorkFrames('platform:resource', (frame) => {
        if (frame.kind === 'workstream') readUsageAgain();
    });
    useWorkFrames('reset', readUsageAgain);

    // The latest read's period, for the charges the table reads after it.
    const period = useRef<UsageRead['period'] | null>(null);
    period.current = data?.period ?? null;
    const charges = useCallback<ChargesSource>(
        async (query, cursor, limit) => {
            const p = period.current;
            if (!p) return NO_CHARGES;
            const answer = await Usage.charges({
                client,
                from: p.window_start,
                to: p.window_end,
                keys: query.keys ?? undefined,
                day: query.day ?? undefined,
                tz: ZONE,
                cursor: cursor ?? undefined,
                limit,
            });
            return pageOf(answer);
        },
        [client]
    );
    const reload = useCallback(() => void refresh(), [refresh]);

    return {
        snap: data?.snap ?? null,
        firstPage: data?.firstPage ?? null,
        error: error === undefined ? null : error instanceof Error ? error.message : 'Usage didn’t load',
        reload,
        charges,
    };
}
