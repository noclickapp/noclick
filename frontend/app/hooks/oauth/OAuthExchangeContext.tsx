// The single seam between the two credential-connection surfaces: the OAuth
// exchange transport. Every provider OAuth hook mints the credential by calling
// `exchange({event_name, ...})` — this context decides HOW/where that lands:
//   - default (in-app): the authed socket via sendEventAsync → stores for the current user.
//   - provide page: an HTTP shim (provideLinkTransport) → stores for the requester.
// The hooks are otherwise identical across both surfaces, so nothing about the
// provider flows (authorize URL, scopes, PKCE, quirks) can diverge between them.

import { createContext, useContext } from 'react';
import { sendEventAsync } from '~/lib/socket-sender';

// A `sendEventAsync`-shaped function: takes an event object (with `event_name`)
// and resolves to the response. Same contract the socket sender already exposes,
// so the default is a zero-cost passthrough.
export type OAuthExchange = (event: any) => Promise<any>;

const OAuthExchangeContext = createContext<OAuthExchange>(sendEventAsync);

export const OAuthExchangeProvider = OAuthExchangeContext.Provider;

/** The exchange transport for the current surface (socket unless overridden). */
export function useOAuthExchange(): OAuthExchange {
    return useContext(OAuthExchangeContext);
}
