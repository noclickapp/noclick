// What every console read sits under: the client and its context, tooltips, the
// account (`/v1/account`) and the platform:resource frames, from the host's live
// source when it has one, that make reads stale. The console mounts it, the
// tests' harness does, and so does any other screen that reads the
// platform the same way.
import { useEffect, type ReactNode } from 'react';
import { PermissionDenied } from 'noclick';
import { TooltipProvider } from '@/ui/tooltip';
import { ClientProvider } from '@/sdk/client';
import type { WorkLive } from '@/sdk/live';
import { getAccount } from '@/sdk/owner';
import { staleReads } from '@/sdk/staleReads';
import { AccountContext, ConsoleContext, useConsole, type ConsoleContextValue } from '@/screens/console/hooks/useConsole';
import { invalidateV1, useV1 } from '@/sdk/useV1';
import { AccountNotRead } from './AccountNotRead';

export const ACCOUNT_POLL_MS = 60_000;

function AccountProvider({ children }: { children: ReactNode }) {
    const { client, actsAs } = useConsole();
    const account = useV1('account', (signal) => getAccount(client, signal), { pollMs: ACCOUNT_POLL_MS });
    // A key the API won't read the account to: no page could say truthfully what the account has.
    if (actsAs === 'key' && account.data === undefined && account.error instanceof PermissionDenied) return <AccountNotRead error={account.error} />;
    return <AccountContext.Provider value={account}>{children}</AccountContext.Provider>;
}

/** Every read showing a resource that moved is read again. */
function useResourceFrames(live: WorkLive | null): void {
    useEffect(
        () =>
            live?.on('platform:resource', (frame) => {
                for (const prefix of staleReads(frame)) invalidateV1(prefix);
            }),
        [live]
    );
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
    useResourceFrames(value.live);
    return (
        <ConsoleScope value={value}>
            <TooltipProvider delayDuration={300}>
                <AccountProvider>{children}</AccountProvider>
            </TooltipProvider>
        </ConsoleScope>
    );
}
