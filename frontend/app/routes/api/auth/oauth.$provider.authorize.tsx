import type { LoaderFunctionArgs } from 'react-router';
import {
    buildGenericAuthorization,
    declaredOAuthProvider,
} from '~/lib/genericOAuth.server';
import { oauthRedirect } from '~/lib/oauthFlow.server';
import { oauthNotConfiguredResponse } from '~/lib/oauthSetupPage.server';

export async function loader({ request, params }: LoaderFunctionArgs) {
    const spec = declaredOAuthProvider(params.provider);
    if (spec.deviceFlow) throw new Response("Provider uses device authorization", { status: 404 });
    const clientId = process.env[spec.clientIdEnv];
    const redirectUri = process.env[spec.redirectUriEnv];
    if (!clientId || !redirectUri)
        return oauthNotConfiguredResponse({
            request,
            provider: spec.provider,
            missing: [
                !clientId && spec.clientIdEnv,
                !redirectUri && spec.redirectUriEnv,
            ].filter((key): key is string => Boolean(key)),
        });
    const rawScopes = new URL(request.url).searchParams.get('scopes');
    const scopes = rawScopes
        ? rawScopes.split(' ').filter(Boolean)
        : spec.scopes;
    return oauthRedirect(
        request,
        buildGenericAuthorization(spec, scopes, clientId, redirectUri, Object.fromEntries(
            Object.entries(spec.contextFields ?? {}).filter(([, field]) => field.source === "input")
                .map(([key]) => [key, new URL(request.url).searchParams.get(key) ?? ""])
        ))
    );
}
