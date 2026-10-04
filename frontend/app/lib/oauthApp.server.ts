// A connect link whose requester brings its own OAuth app for a provider (a
// developer's, named on their brand) signs in with that app, so the consent
// screen names them. The provide page passes its link token as `oauth_app`;
// the authorize route asks the backend for the app's client id, which is
// public anyway (it rides every consent URL). The secret never leaves the
// backend, which exchanges the code with it and keeps it on the credential.

import { apiBaseUrl } from '~/lib/hostedDefaults';

/**
 * The client id of the OAuth app the link names for `provider`, or null when
 * there's no link or it signs in with this instance's own app. A link whose
 * app can't be used (its secret deleted, the link spent) stops the sign-in
 * with the reason, rather than asking consent for another app.
 */
export async function oauthAppClientId(token: string | null, provider: string): Promise<string | null> {
    if (!token) return null;
    const res = await fetch(
        `${apiBaseUrl()}/api/credential-request/${encodeURIComponent(token)}/oauth-client/${encodeURIComponent(provider)}`
    );
    if (!res.ok) {
        const detail = ((await res.json().catch(() => ({}))) as { detail?: string }).detail;
        throw new Response(detail || "This link can't sign in right now. Ask for a new one.", { status: res.status });
    }
    return ((await res.json()) as { client_id: string | null }).client_id;
}

/** The link token a provide page's sign-in carries (`?oauth_app=`), if any. */
export function oauthAppToken(request: Request): string | null {
    return new URL(request.url).searchParams.get('oauth_app');
}
