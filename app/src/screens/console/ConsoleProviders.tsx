// What every console read sits under: the client and its context, tooltips, the
// account (`/v1/account`) and the frames, from the host's live source when it has
// one, that make reads stale. The console mounts it, the tests' harness does, and
// so does any other screen that reads the platform the same way.
import { useEffect, type ReactNode } from 'react';
import { PermissionDenied } from 'noclick';
import { TooltipProvider } from '@/ui/tooltip';
import { ClientProvider } from '@/sdk/client';
import type { WorkLive } from '@/sdk/live';
import { getAccount } from '@/sdk/owner';
import { staleReads } from '@/sdk/staleReads';
import { AccountContext, ConsoleContext, useConsole, type ConsoleContextValue } from '@/screens/console/hooks/useConsole';
import { coalesced, READ_GAP_MS, type Coalesced } from '@/screens/console/hooks/liveReads';
import { LIVE_OPERATION_STATUSES } from '@/screens/console/lib/status';
import { invalidateV1, useV1 } from '@/sdk/useV1';
import { AccountNotRead } from './AccountNotRead';

/** The account's counts take in kinds that send no frame (keys, users, inboxes, numbers, webhooks, stores, secrets,
 *  cards): read again this often, beside the frames that say it moved. */
export const ACCOUNT_POLL_MS = 60_000;
/** The account read is the heaviest the console makes: at most this often while frames keep saying it moved. */
const ACCOUNT_GAP_MS = 5000;
/** Resources the account counts, whose frames make it stale too. */
const COUNTED = new Set(['machine', 'sandbox', 'mcp_server']);
/** How many operations' last-heard statuses a tab keeps (one that ends is let go). */
const STATUSES_KEPT = 2000;

function AccountProvider({ children }: { children: ReactNode }) {
    const { client, actsAs } = useConsole();
    const account = useV1('account', (signal) => getAccount(client, signal), { pollMs: ACCOUNT_POLL_MS });
    // A key the API won't read the account to: no page could say truthfully what the account has.
    if (actsAs === 'key' && account.data === undefined && account.error instanceof PermissionDenied) return <AccountNotRead error={account.error} />;
    return <AccountContext.Provider value={account}>{children}</AccountContext.Provider>;
}

/**
 * Every read showing what a frame says moved is read again: a resource's (staleReads); an operation's own reads on each
 * of its moves, and the lists and counts it's in when its status moves (made, started, held, ended), not on each line
 * it prints; the account's agents when one is made, changed, deleted or takes a turn; what the account spent when it's
 * charged; and everything shown when too much moved to say. A list or a count is read at most once a READ_GAP_MS (the
 * account once an ACCOUNT_GAP_MS) while frames keep coming, the last never lost.
 */
function useLiveFrames(live: WorkLive | null): void {
    useEffect(() => {
        if (!live) return;
        const later = new Map<string, Coalesced>();
        const stale = (prefix: string, gapMs = READ_GAP_MS) => {
            let reads = later.get(prefix);
            if (!reads) later.set(prefix, (reads = coalesced(() => invalidateV1(prefix), gapMs)));
            reads.kick();
        };
        const statuses = new Map<string, string | null | undefined>();
        const offs = [
            live.on('platform:resource', (frame) => {
                for (const prefix of staleReads(frame)) invalidateV1(prefix);
                if (COUNTED.has(frame.kind)) stale('account', ACCOUNT_GAP_MS);
                if (frame.kind !== 'operation' || (statuses.has(frame.id) && statuses.get(frame.id) === frame.status)) return;
                statuses.delete(frame.id);
                if (frame.status && LIVE_OPERATION_STATUSES.has(frame.status)) statuses.set(frame.id, frame.status);
                if (statuses.size > STATUSES_KEPT) statuses.delete(statuses.keys().next().value!);
                stale('operations?');
                stale('operations/summary');
                stale('account', ACCOUNT_GAP_MS);
            }),
            live.on('platform:agent', (frame) => {
                if (frame.change === 'definition') {
                    invalidateV1(`agents/${frame.agent_id}`);
                    stale('agents?');
                    stale('account', ACCOUNT_GAP_MS);
                } else if (frame.change === 'turn') stale('agents?');
            }),
            live.on('platform:usage', () => {
                stale('usage');
                stale('account', ACCOUNT_GAP_MS);
            }),
            live.on('reset', () => invalidateV1('')),
        ];
        return () => {
            offs.forEach((off) => off());
            later.forEach((reads) => reads.stop());
        };
    }, [live]);
}

/** The console's context, and its client for every read under it (`useV1`). A screen that hands the account in itself
 *  (a test with its own) mounts this, with an `AccountContext.Provider`, in place of `ConsoleProviders`. */
export function ConsoleScope({ value, children }: { value: ConsoleContextValue; children: ReactNode }) {
    return (
        <ConsoleContext.Provider value={value}>
            <ClientProvider client={value.client}>{children}</ClientProvider>
        </ConsoleContext.Provider>
    );
}

export function ConsoleProviders({ value, children }: { value: ConsoleContextValue; children: ReactNode }) {
    useLiveFrames(value.live);
    return (
        <ConsoleScope value={value}>
            <TooltipProvider delayDuration={300}>
                <AccountProvider>{children}</AccountProvider>
            </TooltipProvider>
        </ConsoleScope>
    );
}
