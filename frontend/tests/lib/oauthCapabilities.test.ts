import { afterEach, expect, it, vi } from 'vitest';
import { buildGenericAuthorization } from '~/lib/genericOAuth.server';
import { validateOAuthContext } from '~/lib/oauthContext';
import { loader as authorize } from '~/routes/api/auth/oauth.$provider.authorize';
import { loader as callback } from '~/routes/api/auth/oauth.$provider.callback';
import {
    INTEGRATION_METADATA,
    type PublicOAuthProvider,
} from '~/utils/integrationMetadata';

const spec: PublicOAuthProvider = {
    provider: 'example',
    authorizeUrl: 'https://{host}/{tenant}/authorize',
    scopes: ['read', 'write'],
    pkce: true,
    clientIdEnv: 'EXAMPLE_ID',
    clientSecretEnv: 'EXAMPLE_SECRET',
    redirectUriEnv: 'EXAMPLE_CALLBACK',
    authorizeParams: {},
    credentialType: 'example_oauth',
    scopeSeparator: ',',
    contextFields: {
        host: {
            source: 'input',
            kind: 'host',
            pattern: '[a-z0-9-]+\\.provider\\.example',
            choices: [],
            label: 'Host',
            callbackName: null,
        },
        tenant: {
            source: 'input',
            kind: 'value',
            pattern: '[a-zA-Z0-9_-]+',
            choices: [],
            label: 'Tenant',
            callbackName: null,
        },
        merchant_id: {
            source: 'callback',
            kind: 'value',
            pattern: '[A-Z0-9]+',
            choices: [],
            label: null,
            callbackName: 'merchant_id',
        },
    },
};
const redirectUri = 'https://app.example/api/auth/oauth/example/callback';
afterEach(() => {
    vi.unstubAllEnvs();
    delete INTEGRATION_METADATA.oauthProviders.example;
});

it('builds tenant URLs, comma scopes and PKCE while sealing input context', async () => {
    INTEGRATION_METADATA.oauthProviders.example = {
        ...spec,
        contextFields: {
            ...spec.contextFields,
            accounts_server: {
                source: 'callback',
                kind: 'origin',
                pattern: null,
                choices: [
                    'https://accounts.zoho.com',
                    'https://accounts.zoho.eu',
                ],
                label: null,
                callbackName: 'accounts-server',
            },
        },
    };
    vi.stubEnv('SESSION_SECRET', 'oauth-capability-test-secret-long-enough');
    vi.stubEnv('EXAMPLE_ID', 'client');
    vi.stubEnv('EXAMPLE_CALLBACK', redirectUri);
    const response = await authorize({
        request: new Request(
            'https://app.example/api/auth/oauth/example/authorize?host=eu.provider.example&tenant=company'
        ),
        params: { provider: 'example' },
    } as any);
    const target = new URL(response.headers.get('Location')!);
    expect(target.origin + target.pathname).toBe(
        'https://eu.provider.example/company/authorize'
    );
    expect(target.searchParams.get('scope')).toBe('read,write');
    expect(target.searchParams.get('code_challenge_method')).toBe('S256');
    const request = (
        extra = '&merchant_id=ABC123&accounts-server=https%3A%2F%2Faccounts.zoho.eu'
    ) =>
        new Request(
            `${redirectUri}?code=code&state=${target.searchParams.get('state')}${extra}`,
            {
                headers: {
                    Cookie: response.headers.get('Set-Cookie')!.split(';')[0],
                },
            }
        );
    const result = await callback({
        request: request(),
        params: { provider: 'example' },
    } as any);
    expect(result).toMatchObject({
        context: {
            host: 'eu.provider.example',
            tenant: 'company',
            merchant_id: 'ABC123',
            accounts_server: 'https://accounts.zoho.eu',
        },
    });
    await expect(
        callback({
            request: request('&merchant_id=../bad'),
            params: { provider: 'example' },
        } as any)
    ).rejects.toMatchObject({ status: 400 });
    await expect(
        callback({
            request: new Request(
                `${redirectUri}?code=code&state=${target.searchParams.get('state')}&merchant_id=ABC123`
            ),
            params: { provider: 'example' },
        } as any)
    ).rejects.toMatchObject({ status: 400 });
});

it.each([
    'evil.example',
    'eu.provider.example.evil.test',
    'eu.provider.example@evil.test',
    'eu.provider.example:443',
    '127.0.0.1',
])('refuses unsafe tenant host %s before redirect', (host) => {
    expect(() =>
        buildGenericAuthorization(spec, spec.scopes, 'id', redirectUri, {
            host,
            tenant: 'company',
        })
    ).toThrow();
});

it('allows only declared data centres and rejects missing or injected context', () => {
    const regional: PublicOAuthProvider = {
        ...spec,
        contextFields: {
            accounts: {
                source: 'input',
                kind: 'origin',
                choices: [
                    'https://accounts.zoho.com',
                    'https://accounts.zoho.eu',
                ],
                pattern: null,
                label: 'Data centre',
                callbackName: null,
            },
        },
        authorizeUrl: '{accounts}/oauth/v2/auth',
    };
    expect(
        new URL(
            buildGenericAuthorization(regional, ['read'], 'id', redirectUri, {
                accounts: 'https://accounts.zoho.eu',
            })
        ).hostname
    ).toBe('accounts.zoho.eu');
    expect(() =>
        validateOAuthContext(
            regional,
            { accounts: 'https://accounts.zoho.evil' },
            ['input']
        )
    ).toThrow();
    expect(() => validateOAuthContext(regional, {}, ['input'])).toThrow();
    expect(() =>
        validateOAuthContext(
            regional,
            { accounts: 'https://accounts.zoho.eu', client_secret: 'bad' },
            ['input']
        )
    ).toThrow();
});

it('does not send device providers to a redirect route', () => {
    expect(() =>
        buildGenericAuthorization(
            { ...spec, deviceFlow: true, authorizeUrl: null },
            [],
            '',
            ''
        )
    ).toThrow();
});

it('keeps legacy state and URL parameters identical when options are absent', () => {
    const legacy = {
        ...spec,
        authorizeUrl: 'https://provider.example/authorize',
        contextFields: undefined,
        scopeSeparator: undefined,
    };
    const url = new URL(
        buildGenericAuthorization(legacy, legacy.scopes, 'client', redirectUri)
    );
    expect(url.searchParams.get('scope')).toBe('read write');
    expect(
        JSON.parse(
            Buffer.from(url.searchParams.get('state')!, 'base64url').toString()
        )
    ).not.toHaveProperty('context');
    expect([...url.searchParams.keys()].sort()).toEqual([
        'client_id',
        'code_challenge',
        'code_challenge_method',
        'redirect_uri',
        'response_type',
        'scope',
        'state',
    ]);
});
