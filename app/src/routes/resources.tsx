// `/resources`: what the account owns and what it costs (src/screens/resources), read with the app's key through the
// app's own server, as every screen's calls are. Its links into the developer console open `/developers`, and an
// agent's into `/work`. What only the account's signed-in owner can do (src/screens/console/ownerOnly.ts) isn't
// offered here.
import { useMemo } from 'react';
import { useLoaderData, useNavigate } from 'react-router';
import { useLocaleCountry } from '@/lib/localeCountry';
import { signOut } from '@/lib/signOut';
import { readAccountStatus } from '@/screens/account/status';
import { askInChat } from '@/screens/chat/asks';
import { ConsoleProviders } from '@/screens/console/ConsoleProviders';
import type { ConsoleContextValue } from '@/screens/console/hooks/useConsole';
import { NOCLICK_SITE } from '@/screens/console/lib/site';
import { ResourcesContext, type ResourcesContextValue } from '@/screens/resources/context';
import { ResourcesView } from '@/screens/resources/ResourcesPage';
import { ResourcesReads } from '@/screens/resources/reads';
import { useClient } from '@/sdk/client';
import { useV1 } from '@/sdk/useV1';
import { liveFromWatch, sdkLive } from '@/sdk/watchLive';
import { apiUrl } from '@/server/apiUrl.server';
import type { Route } from './+types/resources';

/** Where the console's pages are, for Resources' links to them. */
const CONSOLE_PATH = '/developers';

export const meta: Route.MetaFunction = () => [{ title: 'Resources · NoClick' }];

/** NoClick's API as code outside this app reaches it, for the commands a page prints. */
export const loader = ({ context }: Route.LoaderArgs) => ({ apiUrl: apiUrl(context) });

/** That address is the same for as long as the app runs: moving between Resources' pages doesn't read it again. */
export const shouldRevalidate = () => false;

export default function Resources() {
    const { apiUrl: api } = useLoaderData<typeof loader>();
    const client = useClient();
    const country = useLocaleCountry();
    // Whose account the key acts in; the page draws without it until it's read.
    const status = useV1('status', (signal) => readAccountStatus(client, signal), { client });
    const account = status.data?.account;
    // The account's change stream, where the API offers it: a resource that moved is read again.
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
            signOut: () => void signOut(account?.id),
            live,
        }),
        [client, api, country, account?.id, account?.email, live]
    );
    // NoClick bills the account, so prices show and what's sold is offered; every workflow the key reads is listed.
    const navigate = useNavigate();
    // An empty kind's Ask NoClick drafts it in this app's chat.
    const resources = useMemo<ResourcesContextValue>(() => ({ billing: true, country, ask: askInChat(navigate) }), [country, navigate]);
    return (
        <ConsoleProviders value={consoleValue}>
            <ResourcesContext.Provider value={resources}>
                <ResourcesReads>
                    {/* The page scrolls inside the window, as it does inside NoClick's own shell. */}
                    <div className="h-dvh">
                        <ResourcesView />
                    </div>
                </ResourcesReads>
            </ResourcesContext.Provider>
        </ConsoleProviders>
    );
}
