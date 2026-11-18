// The SDK client every screen reads, handed in by whoever renders the app: the open app's root gives one that goes
// through its own server (proxiedClient); another host of these screens can give one of its own.
import type { NoClick } from 'noclick';
import { createContext, useContext, type ReactNode } from 'react';

const ClientContext = createContext<NoClick | null>(null);

export function ClientProvider({ client, children }: { client: NoClick; children: ReactNode }) {
    return <ClientContext.Provider value={client}>{children}</ClientContext.Provider>;
}

/** The SDK client for this screen's calls: pass it as `{ client }`, or call its methods. */
export function useClient(): NoClick {
    const client = useContext(ClientContext);
    if (!client) throw new Error('useClient() needs a <ClientProvider> above it; the app’s root route renders one.');
    return client;
}
