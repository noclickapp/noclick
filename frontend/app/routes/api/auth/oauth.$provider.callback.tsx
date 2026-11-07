import { useEffect } from 'react';
import { useLoaderData, type LoaderFunctionArgs } from 'react-router';
import { declaredOAuthProvider } from '~/lib/genericOAuth.server';
import { oauthCallbackUrl } from '~/lib/oauthFlow.server';

export async function loader({ request, params }: LoaderFunctionArgs) {
    const spec = declaredOAuthProvider(params.provider);
    const url = await oauthCallbackUrl(request);
    const error = url.searchParams.get('error');
    if (error)
        return {
            provider: spec.provider,
            success: false,
            error: 'Authorization was refused',
        };
    const code = url.searchParams.get('code');
    if (!code)
        throw new Response('Missing authorization code', { status: 400 });
    const state = JSON.parse(
        Buffer.from(url.searchParams.get('state')!, 'base64url').toString()
    );
    if (state.provider !== spec.provider)
        throw new Response('OAuth provider does not match state', {
            status: 400,
        });
    return {
        provider: spec.provider,
        success: true,
        code,
        redirectUri: state.redirectUri as string,
        scopes: state.scopes as string[],
        codeVerifier: state.codeVerifier as string | undefined,
    };
}

export default function OAuthCallback() {
    const data = useLoaderData<typeof loader>();
    useEffect(() => {
        if (window.opener) {
            window.opener.postMessage(
                { ...data, type: `${data.provider}-oauth-callback` },
                window.location.origin
            );
            window.close();
        }
    }, [data]);
    return (
        <p>
            {data.success
                ? 'Completing connection. You can close this window.'
                : data.error}
        </p>
    );
}
