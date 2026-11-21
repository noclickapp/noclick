// `/settings`: Settings (src/screens/settings), read with the app's key through the app's own server, as every
// screen's calls are. Usage; the plan and the balance, with NoClick's pages for changing them; the monthly spending cap,
// which the key lowers or sets where there's none (raising or removing it is the owner's, on NoClick:
// src/screens/console/ownerOnly.ts); the owner's email alerts; and the way into the developer console. What only a
// deployment has (its people, linking a phone, its builder's skills, its own popups) isn't here. It reads again when the
// account's change stream says something it shows moved, where the API serves the stream, and when the page comes back
// into view: never on a timer.
import { useMemo } from 'react';
import { useLoaderData } from 'react-router';
import { useLocaleCountry } from '@/lib/localeCountry';
import { signOut } from '@/lib/signOut';
import { readAccountStatus } from '@/screens/account/status';
import type { ConsoleContextValue } from '@/screens/console/hooks/useConsole';
import { NOCLICK_SITE } from '@/screens/console/lib/site';
import { AppSettings, SettingsScope } from '@/screens/settings/SettingsPage';
import { useClient } from '@/sdk/client';
import type { WorkLive } from '@/sdk/live';
import { useV1 } from '@/sdk/useV1';
import { liveFromWatch, sdkLive } from '@/sdk/watchLive';
import { apiUrl } from '@/server/apiUrl.server';
import type { Route } from './+types/settings';

/** Where the console's pages are: Developer opens it. */
const CONSOLE_PATH = '/developers';

export const meta: Route.MetaFunction = () => [{ title: 'Settings · NoClick' }];

/** NoClick's API as code outside this app reaches it. */
export const loader = ({ context }: Route.LoaderArgs) => ({ apiUrl: apiUrl(context) });

/** That address is the same for as long as the app runs: moving between Settings' sections doesn't read it again. */
export const shouldRevalidate = () => false;

export default function Settings() {
    const { apiUrl: api } = useLoaderData<typeof loader>();
    const client = useClient();
    const country = useLocaleCountry();
    // Whose account the key acts in; the page draws without it until it's read.
    const status = useV1('status', (signal) => readAccountStatus(client, signal), { client });
    const account = status.data?.account;
    // Never on a timer: a stream the API doesn't serve leaves the page to its focus re-reads.
    const live = useMemo(() => liveFromWatch(sdkLive(client), { backstopMs: null }), [client]);
    const consoleValue = useMemo<ConsoleContextValue & { live: WorkLive }>(
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
            signOut: () => void signOut(account?.id),
            live,
        }),
        [client, api, country, account?.id, account?.email, live]
    );
    return (
        <SettingsScope value={consoleValue}>
            {/* The page fills the frame, as it does inside NoClick's own shell. */}
            <div className="h-full">
                <AppSettings />
            </div>
        </SettingsScope>
    );
}
