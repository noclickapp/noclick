import crypto from 'node:crypto';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
    buildGenericAuthorization,
    declaredOAuthProvider,
} from '~/lib/genericOAuth.server';
import { oauthRedirect, oauthCallbackUrl } from '~/lib/oauthFlow.server';
import {
    INTEGRATION_METADATA,
    type PublicOAuthProvider,
} from '~/utils/integrationMetadata';
import {
    getProviderConfig,
    getProviderConfigByCredentialType,
    getProviderKeyFromCredentialType,
    GENERIC_OAUTH_PROVIDER_CONFIG,
} from '~/utils/oauthProviders';
import { loader as authorize } from '~/routes/api/auth/oauth.$provider.authorize';
import { loader as callback } from '~/routes/api/auth/oauth.$provider.callback';

const spec: PublicOAuthProvider = {
    provider: 'example',
    authorizeUrl: 'https://provider.example/authorize',
    scopes: ['read', 'offline'],
    pkce: true,
    clientIdEnv: 'EXAMPLE_ID',
    clientSecretEnv: 'EXAMPLE_SECRET',
    redirectUriEnv: 'EXAMPLE_CALLBACK',
    authorizeParams: { prompt: 'consent' },
    credentialType: 'example_oauth',
};
const callbackUri = 'https://app.example/api/auth/oauth/example/callback';
afterEach(() => {
    vi.unstubAllEnvs();
    delete INTEGRATION_METADATA.oauthProviders.example;
    delete GENERIC_OAUTH_PROVIDER_CONFIG.example;
});

it('builds state, scopes and S256 PKCE from public metadata', async () => {
    vi.stubEnv(
        'SESSION_SECRET',
        'generic-oauth-secret-long-enough-for-the-test'
    );
    const url = new URL(
        buildGenericAuthorization(spec, spec.scopes, 'client', callbackUri)
    );
    const raw = url.searchParams.get('state')!;
    const state = JSON.parse(Buffer.from(raw, 'base64url').toString());
    expect(state).toMatchObject({
        provider: 'example',
        scopes: ['read', 'offline'],
        redirectUri: callbackUri,
    });
    expect(state.nonce).toBeTruthy();
    expect(url.searchParams.get('code_challenge')).toBe(
        crypto
            .createHash('sha256')
            .update(state.codeVerifier)
            .digest('base64url')
    );
    expect(url.searchParams.get('code_challenge_method')).toBe('S256');
    expect(url.searchParams.get('prompt')).toBe('consent');
    expect(url.searchParams.has('code_verifier')).toBe(false);
    const response = await oauthRedirect(
        new Request('https://app.example/api/auth/oauth/example/authorize'),
        url.toString()
    );
    const sealed = new URL(response.headers.get('Location')!).searchParams.get(
        'state'
    )!;
    expect(sealed).not.toContain(raw);
    const request = new Request(`${callbackUri}?code=code&state=${sealed}`, {
        headers: { Cookie: response.headers.get('Set-Cookie')!.split(';')[0] },
    });
    expect((await oauthCallbackUrl(request)).searchParams.get('state')).toBe(
        raw
    );
    await expect(
        oauthCallbackUrl(
            new Request(`${callbackUri}?code=code&state=${sealed}`)
        )
    ).rejects.toMatchObject({ status: 400 });
});

it('uses declared env names in the actual dynamic authorize and callback loaders', async () => {
    INTEGRATION_METADATA.oauthProviders.example = spec;
    vi.stubEnv(
        'SESSION_SECRET',
        'generic-oauth-secret-long-enough-for-the-test'
    );
    vi.stubEnv('EXAMPLE_ID', 'configured-client');
    vi.stubEnv('EXAMPLE_CALLBACK', callbackUri);
    const response = await authorize({
        request: new Request(
            'https://app.example/api/auth/oauth/example/authorize'
        ),
        params: { provider: 'example' },
        context: {},
    } as any);
    const target = new URL(response.headers.get('Location')!);
    expect(target.searchParams.get('client_id')).toBe('configured-client');
    expect(target.searchParams.get('redirect_uri')).toBe(callbackUri);
    const result = await callback({
        request: new Request(
            `${callbackUri}?code=code&state=${target.searchParams.get('state')}`,
            {
                headers: {
                    Cookie: response.headers.get('Set-Cookie')!.split(';')[0],
                },
            }
        ),
        params: { provider: 'example' },
        context: {},
    } as any);
    expect(result).toMatchObject({
        provider: 'example',
        success: true,
        code: 'code',
        redirectUri: callbackUri,
    });
    expect('codeVerifier' in result && result.codeVerifier).toHaveLength(43);
});

it('omits PKCE when disabled and refuses unregistered providers/scopes', () => {
    expect(
        new URL(
            buildGenericAuthorization(
                { ...spec, pkce: false },
                ['read'],
                'id',
                callbackUri
            )
        ).searchParams.has('code_challenge')
    ).toBe(false);
    expect(() =>
        buildGenericAuthorization(spec, ['admin'], 'id', callbackUri)
    ).toThrow();
    expect(() => declaredOAuthProvider('unknown-example')).toThrow();
    expect(getProviderConfig('constructor')).toBeUndefined();
});

it('resolves generic provider and credential lookups while preserving bespoke precedence', () => {
    GENERIC_OAUTH_PROVIDER_CONFIG.example = {
        name: 'Example',
        Icon: () => null,
        oauthProvider: 'example',
        credentialTypes: ['example_oauth'],
        defaultScopes: ['read'],
    };
    expect(getProviderConfig('example')?.name).toBe('Example');
    expect(
        getProviderConfigByCredentialType('example_oauth')?.oauthProvider
    ).toBe('example');
    expect(getProviderKeyFromCredentialType('example_oauth')).toBe('example');
    expect(getProviderConfig('attio')?.name).toBe('Attio');
});

it.each(['constructor', 'toString', '__proto__'])(
    'refuses inherited provider %s in both loaders',
    async (provider) => {
        for (const loader of [authorize, callback]) {
            await expect(
                loader({
                    request: new Request(
                        `https://app.example/api/auth/oauth/${provider}/authorize`
                    ),
                    params: { provider },
                    context: {},
                } as any)
            ).rejects.toMatchObject({ status: 404 });
        }
    }
);

it('shows both processes env names for a metadata-only provider', async () => {
    INTEGRATION_METADATA.oauthProviders.example = spec;
    const { providerSetup } = await import('~/lib/oauthProviderSetup');
    const { oauthNotConfiguredResponse, callbackUrlFor } = await import(
        '~/lib/oauthSetupPage.server'
    );
    expect(providerSetup('example')).toMatchObject({
        frontendEnv: ['EXAMPLE_ID', 'EXAMPLE_CALLBACK'],
        backendEnv: ['EXAMPLE_ID', 'EXAMPLE_SECRET', 'EXAMPLE_CALLBACK'],
    });
    const request = new Request(
        'https://app.example/api/auth/oauth/example/authorize'
    );
    const response = oauthNotConfiguredResponse({
        request,
        provider: 'example',
    });
    const html = await response.text();
    expect(html).toContain('frontend/.env');
    expect(html).toContain('backend/.env');
    expect(html).toContain('EXAMPLE_SECRET=');
    expect(html.match(/EXAMPLE_ID=/g)).toHaveLength(2);
    expect(
        html.match(
            /EXAMPLE_CALLBACK=https:\/\/app.example\/api\/auth\/oauth\/example\/callback/g
        )
    ).toHaveLength(2);
    expect(html).not.toContain('Settings &rarr; OAuth Apps');
    expect(providerSetup('constructor').frontendEnv).toEqual([]);
    expect(callbackUrlFor(request, 'constructor')).toBe(
        'https://app.example/api/auth/constructor/callback'
    );
});
