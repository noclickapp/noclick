// Self-hosted OAuth apps configured through Settings, made visible to the
// authorize routes. Those routes read `process.env.<PROVIDER>_CLIENT_ID` and
// `_REDIRECT_URI`; rather than rewrite 49 of them to consult a second source,
// this copies the stored value into `process.env` — never over a value that is
// really there, so environment variables keep winning — and each route calls it
// once before reading. See backend/utils/instance_oauth.py, which does the same
// on its side for the client secret.
//
// The value comes from the backend (`/api/public/oauth-app/{provider}`) rather
// than from the table directly: the Remix process has no service-role key on a
// self-hosted install, and giving it one to read a column that is public anyway
// — the client id travels in the consent URL — would be the wrong trade. The
// secret never leaves the backend.
//
// Hosted builds return immediately: this is a self-hosted concept, and the
// hosted service's client ids come from its deployment environment.

import { isLocalEdition } from '~/lib/edition';
import { apiBaseUrl } from '~/lib/hostedDefaults';
import { callbackUrlFor } from '~/lib/oauthSetupPage.server';
import { OAUTH_PROVIDER_SETUP } from '~/lib/oauthProviderSetup';

// The backend applies saves to its own environment immediately, so it is always
// current; this only avoids a round trip per click. Short, because an operator
// who saves a client id and immediately hits Connect must not get the old one.
const CACHE_MS = 5_000;

const cache = new Map<string, { at: number; clientId: string | null }>();

async function fetchClientId(provider: string): Promise<string | null> {
    const hit = cache.get(provider);
    if (hit && Date.now() - hit.at < CACHE_MS) return hit.clientId;
    let clientId: string | null = null;
    try {
        const res = await fetch(`${apiBaseUrl()}/api/public/oauth-app/${encodeURIComponent(provider)}`);
        if (res.ok) clientId = ((await res.json()) as { client_id?: string }).client_id ?? null;
        // 404 is the ordinary "nothing configured" answer, not a failure.
    } catch (e) {
        console.warn(`[instanceOAuth] could not reach the backend for ${provider}:`, e);
        return null; // don't cache a transport failure as "unconfigured"
    }
    cache.set(provider, { at: Date.now(), clientId });
    return clientId;
}

/**
 * Make this instance's stored OAuth app for `provider` visible as environment
 * variables, if one exists and the environment doesn't already define them.
 *
 * The redirect URI is derived from the incoming request rather than stored: it
 * is always this instance's own callback route, so an operator who changes port
 * or hostname doesn't have to remember to update it.
 */
export async function applyInstanceOAuthEnv(request: Request, provider: string): Promise<void> {
    if (!isLocalEdition()) return;
    // Read the variable NAMES from the generated per-provider map rather than
    // building them from the provider key. Most are <PROVIDER>_CLIENT_ID, but
    // Facebook's route reads FACEBOOK_APP_ID / FACEBOOK_OAUTH_REDIRECT_URI —
    // and a value written to a name nothing reads looks exactly like a save
    // that worked, right up until Connect still says "not configured".
    const frontendEnv = OAUTH_PROVIDER_SETUP[provider]?.frontendEnv ?? [];
    const stem = provider.toUpperCase();
    const redirectVar = frontendEnv.find((v) => v.endsWith('REDIRECT_URI')) ?? `${stem}_REDIRECT_URI`;
    const idVar = frontendEnv.find((v) => v !== redirectVar) ?? `${stem}_CLIENT_ID`;
    if (process.env[idVar] && process.env[redirectVar]) return;

    const clientId = await fetchClientId(OAUTH_PROVIDER_SETUP[provider]?.appOf ?? provider);
    if (!clientId) return;
    if (!process.env[idVar]) process.env[idVar] = clientId;
    if (!process.env[redirectVar]) process.env[redirectVar] = callbackUrlFor(request, provider);
}

/** Reset the read cache — for tests, and after a write from this process. */
export function clearInstanceOAuthCache(): void {
    cache.clear();
}
