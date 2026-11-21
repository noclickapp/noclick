// The accounts Connections lists, from the Provider around the page (the `connections.reads` slot: the platform API's
// connections by default), and how an account the API lists becomes one the page shows: its catalog app, its name as
// whoever names accounts says it (`connection.mark`), and how it's connected again.
import { createContext, useCallback, useContext, useMemo } from 'react';
import type { Connection } from 'noclick';
import { useSlot } from '@/slots';
import { useClient } from '@/sdk/client';
import { reconnectByLink } from '@/ui/connectStandards';
import { CONNECT_APP, CONNECTION_MARK } from '@/ui/slots';
import { accountOf, credentialIdOf, namingFacts } from './apiAccounts';
import { servicesByType, type CatalogApp, type ConnectedAccount } from './model';
import { APPS } from './slots';

export interface ConnectionsAccounts {
    /** Every account you can use, the broken ones first; empty until `loaded`. */
    accounts: ConnectedAccount[];
    loaded: boolean;
    /** Why they couldn't be read, where they couldn't; `retry` reads them again. */
    error: string | null;
    retry: () => void;
}

export const ConnectionsAccountsContext = createContext<ConnectionsAccounts | null>(null);

/** The accounts the page lists, from the Provider around it. */
export function useConnectionsAccounts(): ConnectionsAccounts {
    const accounts = useContext(ConnectionsAccountsContext);
    if (!accounts) throw new Error('Connections reads its accounts from a Provider around it: the `connections.reads` slot gives one.');
    return accounts;
}

/** The catalog app each credential type signs in to: the first that takes it. */
export function useServicesByType(): Map<string, CatalogApp> {
    const apps = useSlot(APPS).useApps();
    return useMemo(() => servicesByType(apps), [apps]);
}

/** How the page makes an account of a connection the API lists, with the page's client. */
export function useAccountMaker(): (connection: Connection) => ConnectedAccount {
    const client = useClient();
    const byType = useServicesByType();
    const { account: names } = useSlot(CONNECTION_MARK);
    const { reconnect } = useSlot(CONNECT_APP);
    return useCallback(
        (connection: Connection) => {
            const service = connection.credentialType ? byType.get(connection.credentialType) : undefined;
            const facts = namingFacts(connection);
            const title = service?.label ?? names(facts).app;
            return accountOf(connection, {
                service,
                names: names(facts),
                // An account connected in the app is connected again in place; a named connection at its own connect page.
                reconnect: () =>
                    connection.origin === 'app'
                        ? reconnect({ credentialType: connection.credentialType ?? undefined, credentialId: credentialIdOf(connection) }, client, title)
                        : void reconnectByLink(client, connection, title),
            });
        },
        [client, byType, names, reconnect]
    );
}
