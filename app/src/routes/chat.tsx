// `/chat`: the account's NoClick to talk to (src/screens/chat), NoClick's one session read and written with the app's
// key through the app's own server, as every screen's calls are. Whoever is signed in to this app talks to it as the
// account: they read its whole thread and memories, and send it the key's power (README, "Chat"). What only the
// account's signed-in owner can do (src/screens/console/ownerOnly.ts: approving a held purchase, adding funds, linking
// a phone) opens NoClick's own page. It follows the account's change stream (@/sdk/watchLive) where the API offers it;
// the conversation itself is live through its own stream either way.
import { useMemo } from 'react';
import { useLoaderData } from 'react-router';
import { useLocaleCountry } from '@/lib/localeCountry';
import { signOut } from '@/lib/signOut';
import { readAccountStatus } from '@/screens/account/status';
import { ChatPage, ThreadLoading } from '@/screens/chat/ChatPage';
import { ChatContext } from '@/screens/chat/context';
import { CoordinatorChat } from '@/screens/chat/CoordinatorChat';
import { ConsoleProviders } from '@/screens/console/ConsoleProviders';
import type { ConsoleContextValue } from '@/screens/console/hooks/useConsole';
import { NOCLICK_SITE } from '@/screens/console/lib/site';
import { WorkNotice } from '@/screens/work/notices';
import { useClient } from '@/sdk/client';
import { liveFromWatch, sdkLive } from '@/sdk/watchLive';
import { useV1 } from '@/sdk/useV1';
import { apiUrl } from '@/server/apiUrl.server';
import type { Route } from './+types/chat';

/** Where the console's pages are, for the links the chat makes to them. */
const CONSOLE_PATH = '/developers';
const NO_VALUES = {};

export const meta: Route.MetaFunction = () => [{ title: 'Chat · NoClick' }];

/** NoClick's API as code outside this app reaches it, for the commands a page prints. */
export const loader = ({ context }: Route.LoaderArgs) => ({ apiUrl: apiUrl(context) });

export const shouldRevalidate = () => false;

export default function ChatRoute() {
    const { apiUrl: api } = useLoaderData<typeof loader>();
    const client = useClient();
    const country = useLocaleCountry();
    // Whose account the key acts in: the chat is the account's, never one of its users'.
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
            signOut: () => void signOut(account?.id),
            live: null,
        }),
        [client, api, country, account?.id, account?.email]
    );
    return (
        <ConsoleProviders value={consoleValue}>
            <div className="h-dvh bg-background text-foreground">
                {status.data === undefined ? (
                    status.error === undefined ? (
                        <ThreadLoading />
                    ) : (
                        <WorkNotice title="Couldn’t reach NoClick" body="The account this app acts in couldn’t be read. Check its key and connection, then try again." action={{ label: 'Try again', onClick: () => void status.refresh() }} />
                    )
                ) : status.data.actingFor ? (
                    <WorkNotice title="Chat is the account’s" body="This app’s key acts for one of the account’s users, and the chat is the account’s own NoClick: give the app one of the account’s own keys." />
                ) : (
                    <ChatContext.Provider value={NO_VALUES}>
                        <CoordinatorChat client={client} live={live}>
                            <ChatPage />
                        </CoordinatorChat>
                    </ChatContext.Provider>
                )}
            </div>
        </ConsoleProviders>
    );
}
