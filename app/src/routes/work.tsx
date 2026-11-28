// `/work`: the account's spaces, their channels and DMs, its agents and the people it works with (src/screens/work),
// read with the app's key through the app's own server, as every screen's calls are. What only the account's
// signed-in owner can do (src/screens/console/ownerOnly.ts) isn't offered here, and whoever is signed in to this app is
// the account: they post as it and read what it reads. What it shows follows the account's change stream (@/sdk/watchLive)
// where the API offers it; while the stream isn't live, it's read again when the page is focused and every minute. An
// agent's open session is live through its own stream either way. Work hands the command palette its channels, DMs,
// agents and spaces while it's open: each moves within Work's own address.
import { useEffect, useMemo } from 'react';
import { useLoaderData, useNavigate } from 'react-router';
import { useLocaleCountry } from '@/lib/localeCountry';
import { signOut } from '@/lib/signOut';
import { askInChat } from '@/screens/chat/asks';
import { readAccountStatus } from '@/screens/account/status';
import { ConsoleProviders } from '@/screens/console/ConsoleProviders';
import type { ConsoleContextValue } from '@/screens/console/hooks/useConsole';
import { NOCLICK_SITE } from '@/screens/console/lib/site';
import { openCommandPalette } from '@/screens/shell/palette/open';
import { rememberPaletteEntries } from '@/screens/shell/palette/sources';
import { workflowRoute } from '@/screens/workflows/routes';
import type { WorkContextValue } from '@/screens/work/context';
import { WorkLoading, WorkNotice } from '@/screens/work/notices';
import { WorkScreen } from '@/screens/work/WorkScreen';
import { useClient } from '@/sdk/client';
import { liveFromWatch, sdkLive } from '@/sdk/watchLive';
import { useV1 } from '@/sdk/useV1';
import { apiUrl } from '@/server/apiUrl.server';
import type { Route } from './+types/work';

/** Where the console's pages are, for Work's links to them. */
const CONSOLE_PATH = '/developers';

export const meta: Route.MetaFunction = () => [{ title: 'Work · NoClick' }];

/** NoClick's API as code outside this app reaches it, for the commands a page prints. */
export const loader = ({ context }: Route.LoaderArgs) => ({ apiUrl: apiUrl(context) });

/** That address is the same for as long as the app runs: moving around Work doesn't read it again. */
export const shouldRevalidate = () => false;

export default function WorkRoute() {
    const { apiUrl: api } = useLoaderData<typeof loader>();
    const client = useClient();
    const country = useLocaleCountry();
    const navigate = useNavigate();
    // Whose account the key acts in: Work is the account's, and what it keeps in this browser is kept under its id.
    const status = useV1('status', (signal) => readAccountStatus(client, signal), { client });
    const account = status.data?.account;
    const live = useMemo(() => liveFromWatch(sdkLive(client)), [client]);
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
            live: null,
        }),
        [client, api, country, account?.id, account?.email]
    );
    // Resources, Connections, the chat and a workflow's page are this app's own pages.
    const work = useMemo<WorkContextValue>(
        () => ({
            ask: askInChat(navigate),
            openPage: (page, params = {}) => {
                const search = new URLSearchParams(Object.entries(params).filter((entry): entry is [string, string] => !!entry[1]));
                navigate(`/${page}${search.size ? `?${search}` : ''}`);
            },
            openWorkflow: (workflow) => navigate(workflowRoute(workflow.id)),
            palette: { remember: (entries) => rememberPaletteEntries('Work', entries), open: () => openCommandPalette() },
        }),
        [navigate]
    );
    // Leaving Work takes its places out of the palette: each one moves within Work's address, not to it.
    useEffect(() => () => rememberPaletteEntries('Work', []), []);
    const user = { email: account?.email ?? '', display_name: account?.name ?? undefined };
    return (
        <ConsoleProviders value={consoleValue}>
            {/* The page fills the frame, as it does inside NoClick's own shell. */}
            <div className="h-full">
                {status.data === undefined ? (
                    status.error === undefined ? (
                        <WorkLoading />
                    ) : (
                        <WorkNotice title="Couldn’t reach NoClick" body="The account this app acts in couldn’t be read. Check its key and connection, then try again." action={{ label: 'Try again', onClick: () => void status.refresh() }} />
                    )
                ) : status.data.actingFor ? (
                    <WorkNotice title="Work is the account’s" body="This app’s key acts for one of the account’s users, and Work shows what the account itself sees: give the app one of the account’s own keys." />
                ) : (
                    <WorkScreen client={client} live={live} keptAs={account?.id ?? null} user={user} work={work} />
                )}
            </div>
        </ConsoleProviders>
    );
}
