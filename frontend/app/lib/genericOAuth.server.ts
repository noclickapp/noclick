import crypto from 'node:crypto';
import { validateOAuthContext, oauthEndpoint } from './oauthContext';
import type { PublicOAuthProvider } from '~/utils/integrationMetadata';
import { INTEGRATION_METADATA } from '~/utils/integrationMetadata';

export function declaredOAuthProvider(
    provider: string | undefined
): PublicOAuthProvider {
    const providers = INTEGRATION_METADATA.oauthProviders;
    const spec = provider && Object.hasOwn(providers, provider) ? providers[provider] : undefined;
    if (!spec) throw new Response('Unknown OAuth provider', { status: 404 });
    return spec;
}

/** Raw state is encrypted and browser-bound by oauthRedirect before leaving us. */
export function buildGenericAuthorization(
    spec: PublicOAuthProvider,
    scopes: string[],
    clientId: string,
    redirectUri: string,
    inputContext?: Record<string, string>
) {
    if (!spec.authorizeUrl || spec.deviceFlow) throw new Response("Provider uses device authorization", { status: 404 });
    let context: Record<string, string>;
    try { context = validateOAuthContext(spec, inputContext ?? {}, ['input']); }
    catch { throw new Response('Invalid OAuth connection input', { status: 400 }); }
    if (scopes.some((scope) => !spec.scopes.includes(scope)))
        throw new Response('Unknown OAuth scope', { status: 400 });
    const verifier = spec.pkce
        ? crypto.randomBytes(32).toString('base64url')
        : undefined;
    const state = Buffer.from(
        JSON.stringify({
            provider: spec.provider,
            ...(spec.contextFields ? { context } : {}),
            scopes,
            codeVerifier: verifier,
            redirectUri,
            nonce: crypto.randomUUID(),
            timestamp: Date.now(),
        })
    ).toString('base64url');
    const url = new URL(oauthEndpoint(spec.authorizeUrl, spec, context));
    for (const [key, value] of Object.entries(spec.authorizeParams))
        url.searchParams.set(key, value);
    for (const [key, value] of Object.entries({
        client_id: clientId,
        redirect_uri: redirectUri,
        response_type: 'code',
        scope: scopes.join(spec.scopeSeparator ?? ' '),
        state,
    }))
        url.searchParams.set(key, value);
    if (verifier) {
        url.searchParams.set(
            'code_challenge',
            crypto.createHash('sha256').update(verifier).digest('base64url')
        );
        url.searchParams.set('code_challenge_method', 'S256');
    }
    return url.toString();
}
