// `/developers/*`: NoClick's developer console (src/screens/console) for the account this app's key acts in. Its
// calls go through the app's own server, as every screen's do, so the console acts as that key: what only the
// account's signed-in owner can do (src/screens/console/ownerOnly.ts) isn't offered here.
import { useMemo } from 'react';
import { useLoaderData, useParams } from 'react-router';
import { useLocaleCountry } from '@/lib/localeCountry';
import { signOut } from '@/lib/signOut';
import { readAccountStatus } from '@/screens/account/status';
import { DeveloperConsole } from '@/screens/console/DeveloperConsole';
import { NOCLICK_SITE } from '@/screens/console/lib/site';
import { useClient } from '@/sdk/client';
import { useV1 } from '@/sdk/useV1';
import { liveFromWatch, sdkLive } from '@/sdk/watchLive';
import { apiUrl } from '@/server/apiUrl.server';
import type { Route } from './+types/developers';

const CONSOLE_PATH = '/developers';

export const meta: Route.MetaFunction = () => [{ title: 'Developers · NoClick' }];

/** NoClick's API as code outside this app reaches it, for the commands the console prints. */
export const loader = ({ context }: Route.LoaderArgs) => ({ apiUrl: apiUrl(context) });

/** That address is the same for as long as the app runs: moving between the console's pages doesn't read it again. */
export const shouldRevalidate = () => false;

export default function Developers() {
    const { apiUrl: api } = useLoaderData<typeof loader>();
    const client = useClient();
    const params = useParams();
    const country = useLocaleCountry();
    // Whose account the key acts in, for the account menu; the console draws without it until it's read.
    const status = useV1('status', (signal) => readAccountStatus(client, signal), { client });
    const account = status.data?.account;
    const user = useMemo(() => ({ id: account?.id ?? '', email: account?.email ?? null }), [account?.id, account?.email]);
    // The account's change stream, where the API offers it: a resource that moved is read again.
    const live = useMemo(() => liveFromWatch(sdkLive(client), { backstopMs: null }), [client]);
    return (
        <DeveloperConsole
            section={params['*']}
            client={client}
            actsAs="key"
            basePath={CONSOLE_PATH}
            apiUrl={api}
            site={NOCLICK_SITE}
            home="/"
            country={country}
            user={user}
            onSignOut={() => void signOut()}
            live={live}
        />
    );
}
