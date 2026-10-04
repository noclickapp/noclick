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

// What a sign-in adds to its authorize request. The provide page names its link
// (`oauth_app`) when the requester brings its own OAuth app, which the authorize
// route then asks consent for (lib/oauthApp.server.ts). Empty elsewhere.
const OAuthAuthorizeContext = createContext<Record<string, string>>({});

export const OAuthAuthorizeProvider = OAuthAuthorizeContext.Provider;

/** The extra authorize-request fields for the current surface. */
export function useOAuthAuthorizeParams(): Record<string, string> {
    return useContext(OAuthAuthorizeContext);
}
