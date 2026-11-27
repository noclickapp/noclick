// `/connections`: the apps and accounts the account's agents and automations act through (src/screens/connections),
// read with the app's key through the app's own server, as every screen's calls are. An account is connected, and
// connected again, at its connect page on NoClick in a new tab: no secret passes through this app. What only the
// account's signed-in owner can do (src/screens/console/ownerOnly.ts: sharing an account, lifting its approvals) opens
// NoClick's own page. It follows the account's change stream (@/sdk/watchLive) where the API offers it.
import { useMemo } from 'react';
import { useLoaderData } from 'react-router';
import { useLocaleCountry } from '@/lib/localeCountry';
import { signOut } from '@/lib/signOut';
import { readAccountStatus } from '@/screens/account/status';
import { ConnectionsView } from '@/screens/connections/ConnectionsPage';
import { ConsoleProviders } from '@/screens/console/ConsoleProviders';
import type { ConsoleContextValue } from '@/screens/console/hooks/useConsole';
import { NOCLICK_SITE } from '@/screens/console/lib/site';
import { useClient } from '@/sdk/client';
import { useV1 } from '@/sdk/useV1';
import { liveFromWatch, sdkLive } from '@/sdk/watchLive';
import { apiUrl } from '@/server/apiUrl.server';
import type { Route } from './+types/connections';

/** Where the console's pages are, for the links a page makes to them. */
const CONSOLE_PATH = '/developers';

export const meta: Route.MetaFunction = () => [{ title: 'Connections · NoClick' }];

/** NoClick's API as code outside this app reaches it, for the commands a page prints. */
export const loader = ({ context }: Route.LoaderArgs) => ({ apiUrl: apiUrl(context) });

/** That address is the same for as long as the app runs: moving between Connections' tabs doesn't read it again. */
export const shouldRevalidate = () => false;

export default function Connections() {
    const { apiUrl: api } = useLoaderData<typeof loader>();
    const client = useClient();
    const country = useLocaleCountry();
    // Whose account the key acts in; the page draws without it until it's read.
    const status = useV1('status', (signal) => readAccountStatus(client, signal), { client });
    const account = status.data?.account;
    // The account's change stream, where the API offers it: a connection that moved is read again.
    const live = useMemo(() => liveFromWatch(sdkLive(client), { backstopMs: null }), [client]);
    const consoleValue = useMemo<ConsoleContextValue>(
        () => ({
            client,
            actsAs: 'key',
            basePath: CONSOLE_PATH,
            apiUrl: api,
            site: NOCLICK_SITE,
            home: '/',
            country,
            user: { id: account?.id ?? '', email: account?.email ?? null },
            now: Date.now,
            lab: false,
            signOut: () => void signOut(),
            live,
        }),
        [client, api, country, account?.id, account?.email, live]
    );
    return (
        <ConsoleProviders value={consoleValue}>
            {/* The page scrolls inside the frame, as it does inside NoClick's own shell. */}
            <div className="h-full">
                <ConnectionsView />
            </div>
        </ConsoleProviders>
    );
}
