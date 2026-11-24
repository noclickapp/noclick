// The SDK client every screen reads, handed in by whoever renders the app: the open app's root gives one that goes
// through its own server (proxiedClient); another host of these screens can give one of its own.
import type { NoClick } from 'noclick';
import { createContext, useContext, type ReactNode } from 'react';

const ClientContext = createContext<NoClick | null>(null);
const OwnerAcceptsContext = createContext(false);

/** `ownerAccepts`: the client's key is one NoClick gave this app (a copy deployed on NoClick), which never accepts
 *  terms for a person; the account's owner accepts them when they approve the call (src/sdk/held.ts). A provider that
 *  doesn't say (a console's, over the same client) keeps what the one above it said. */
export function ClientProvider({ client, ownerAccepts, children }: { client: NoClick; ownerAccepts?: boolean; children: ReactNode }) {
    const above = useContext(OwnerAcceptsContext);
    return (
        <ClientContext.Provider value={client}>
            <OwnerAcceptsContext.Provider value={ownerAccepts ?? above}>{children}</OwnerAcceptsContext.Provider>
        </ClientContext.Provider>
    );
}

/** The client a provider above gives, or null when there is none: for code that may be handed one another way. */
export function useProvidedClient(): NoClick | null {
    return useContext(ClientContext);
}

/** The SDK client for this screen's calls: pass it as `{ client }`, or call its methods. */
export function useClient(): NoClick {
    const client = useContext(ClientContext);
    if (!client) throw new Error('useClient() needs a <ClientProvider> above it; the app’s root route renders one.');
    return client;
}

/** Whether terms a call records a person accepting (a domain's registration agreement, a trademark notice) are left to
 *  the account's owner, who accepts them approving the call: true where the client's key is one NoClick gave this app. */
export function useOwnerAccepts(): boolean {
    return useContext(OwnerAcceptsContext);
}
