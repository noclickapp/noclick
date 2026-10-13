// Exercise Marketplace entry, owner binding and callback persistence without
// contacting a provider. The real sealed-state/browser-cookie seam remains in
// these tests so an accidental state-validation bypass cannot look successful.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { LoaderFunctionArgs } from 'react-router';
import { oauthCallbackUrl } from '~/lib/oauthFlow.server';

const auth = vi.hoisted(() => ({ requireAuth: vi.fn() }));
vi.mock('~/lib/supabase', () => ({
    ...auth,
    createServiceRoleClient: vi.fn(),
}));
vi.mock('~/lib/instanceOAuth.server', () => ({
    applyInstanceOAuthEnv: vi.fn(),
}));
vi.mock('~/lib/oauthApp.server', () => ({
    oauthAppClientId: vi.fn().mockResolvedValue(null),
    oauthAppToken: vi.fn().mockReturnValue(null),
}));
vi.mock('~/lib/hostedDefaults', () => ({
    apiBaseUrl: () => 'https://api.example.test',
}));

import { loader as install } from '~/routes/api/auth/pipedrive.install';
import { loader as authorize } from '~/routes/api/auth/pipedrive.authorize';
import { loader as callback } from '~/routes/api/auth/pipedrive.callback';

const origin = 'https://frontend.example.test';
const userId = '11111111-1111-1111-1111-111111111111';
const credentialId = '22222222-2222-2222-2222-222222222222';
const args = (request: Request) =>
    ({ request, params: {}, context: {} }) as LoaderFunctionArgs;
const req = (path: string, cookie?: string) =>
    new Request(
        origin + path,
        cookie ? { headers: { Cookie: cookie } } : undefined
    );
const fetchMock = vi.fn();

async function flow(mode = 'install') {
    const response = await authorize(
        args(req(`/api/auth/pipedrive/authorize?mode=${mode}`))
    );
    const state = new URL(response.headers.get('Location')!).searchParams.get(
        'state'
    )!;
    // requireAuth's rotated session cookie and oauthRedirect's binding cookie
    // must both survive. Extract only the binding cookie for this fake browser.
    const cookie = response.headers
        .getSetCookie()
        .find((value) => value.startsWith('nc_oauth_pipedrive='))!
        .split(';')[0];
    return { response, state, cookie };
}

describe('Pipedrive Marketplace installation', () => {
    beforeEach(() => {
        vi.stubEnv(
            'SESSION_SECRET',
            'pipedrive-install-unit-test-session-secret'
        );
        vi.stubEnv('PIPEDRIVE_CLIENT_ID', 'test-client');
        vi.stubEnv(
            'PIPEDRIVE_REDIRECT_URI',
            `${origin}/api/auth/pipedrive/callback`
        );
        auth.requireAuth.mockReset().mockImplementation(async () => ({
            user: { id: userId },
            session: { access_token: 'test-session' },
            headers: new Headers({
                'Set-Cookie': 'rotated-session=test; Path=/',
            }),
        }));
        fetchMock
            .mockReset()
            .mockResolvedValue(
                Response.json({ success: true, credential_id: credentialId })
            );
        vi.stubGlobal('fetch', fetchMock);
    });
    afterEach(() => {
        vi.unstubAllEnvs();
        vi.unstubAllGlobals();
    });

    it('discards a stateless Marketplace code before starting a clean install', async () => {
        const response = await callback(
            args(req('/api/auth/pipedrive/callback?code=unbound-code'))
        );
        expect(response.headers.get('Location')).toBe(
            '/api/auth/pipedrive/install'
        );
        expect(response.headers.get('Referrer-Policy')).toBe('no-referrer');
        expect(response.headers.get('Cache-Control')).toContain('no-store');
        expect(await response.text()).not.toContain('unbound-code');
        expect(fetchMock).not.toHaveBeenCalled();
        expect(auth.requireAuth).not.toHaveBeenCalled();
    });

    it.each(['new user', 'signed-out user'])(
        'preserves a clean install destination through login for a %s',
        async () => {
            auth.requireAuth.mockImplementation(async (request: Request) => {
                const url = new URL(request.url);
                throw new Response(null, {
                    status: 302,
                    headers: {
                        Location: `/auth/login?next=${encodeURIComponent(url.pathname + url.search)}`,
                    },
                });
            });
            try {
                await install(
                    args(
                        req(
                            '/api/auth/pipedrive/install?code=untrusted&next=https://evil.example'
                        )
                    )
                );
                throw new Error('expected login redirect');
            } catch (response) {
                expect(response).toBeInstanceOf(Response);
                expect(
                    (response as Response).headers.get('Referrer-Policy')
                ).toBe('no-referrer');
                const location = (response as Response).headers.get(
                    'Location'
                )!;
                expect(new URL(location, origin).searchParams.get('next')).toBe(
                    '/api/auth/pipedrive/install'
                );
                expect(location).not.toContain('untrusted');
                expect(location).not.toContain('evil');
            }
            expect(fetchMock).not.toHaveBeenCalled();
        }
    );

    it('retains rotated auth cookies when the instance is not configured', async () => {
        vi.stubEnv('PIPEDRIVE_CLIENT_ID', '');
        const response = await authorize(
            args(req('/api/auth/pipedrive/authorize?mode=install'))
        );
        expect(response.headers.get('Set-Cookie')).toContain('rotated-session');
        expect(response.headers.get('Cache-Control')).toContain('no-store');
        expect(await response.text()).toContain('PIPEDRIVE_REDIRECT_URI');
        expect(fetchMock).not.toHaveBeenCalled();
    });

    it('takes a signed-in user from install entry to bound consent', async () => {
        const entry = await install(args(req('/api/auth/pipedrive/install')));
        expect(entry.headers.get('Location')).toBe(
            '/api/auth/pipedrive/authorize?mode=install'
        );
        const { response, state, cookie } = await flow();
        expect(response.headers.getSetCookie()).toContain(
            'rotated-session=test; Path=/'
        );
        const restored = await oauthCallbackUrl(
            req(
                `/api/auth/pipedrive/callback?code=bound-code&state=${state}`,
                cookie
            )
        );
        expect(
            JSON.parse(
                Buffer.from(
                    restored.searchParams.get('state')!,
                    'base64url'
                ).toString()
            )
        ).toMatchObject({ mode: 'install', userId });
    });

    it('persists server-side and redirects to credentials without returning the code', async () => {
        const { state, cookie } = await flow();
        const response = await callback(
            args(
                req(
                    `/api/auth/pipedrive/callback?code=bound-code&state=${state}`,
                    cookie
                )
            )
        );
        expect(response.status).toBe(302);
        expect(response.headers.get('Location')).toBe(
            `/dashboard?tab=settings&section=credentials&account=${credentialId}`
        );
        expect(response.headers.get('Set-Cookie')).toContain('rotated-session');
        expect(response.headers.get('Cache-Control')).toContain('no-store');
        expect(await response.text()).not.toContain('bound-code');
        expect(fetchMock).toHaveBeenCalledOnce();
        const [endpoint, init] = fetchMock.mock.calls[0];
        expect(endpoint).toBe(
            'https://api.example.test/api/credential-request/pipedrive/install/exchange'
        );
        expect(init.headers.authorization).toBe('Bearer test-session');
        expect(JSON.parse(init.body)).toEqual({
            code: 'bound-code',
            redirect_uri: `${origin}/api/auth/pipedrive/callback`,
        });
        const authRequest = auth.requireAuth.mock.calls.at(-1)![0] as Request;
        expect(authRequest.url).toBe(`${origin}/api/auth/pipedrive/install`);
    });

    it('rejects a changed NoClick account before exchanging the code', async () => {
        const { state, cookie } = await flow();
        auth.requireAuth.mockResolvedValue({
            user: { id: 'other-user' },
            session: { access_token: 'other-session' },
            headers: new Headers({ 'Set-Cookie': 'rotated=other' }),
        });
        const response = await callback(
            args(
                req(
                    `/api/auth/pipedrive/callback?code=bound-code&state=${state}`,
                    cookie
                )
            )
        );
        expect(await response.json()).toMatchObject({
            success: false,
            mode: 'install',
            error: expect.stringContaining('account changed'),
        });
        expect(response.headers.get('Set-Cookie')).toBe('rotated=other');
        expect(fetchMock).not.toHaveBeenCalled();
    });

    it('restarts an expired NoClick session without carrying the code to login', async () => {
        const { state, cookie } = await flow();
        auth.requireAuth.mockImplementation(async (request: Request) => {
            expect(request.url).toBe(`${origin}/api/auth/pipedrive/install`);
            throw new Response(null, {
                status: 302,
                headers: {
                    Location:
                        '/auth/login?next=%2Fapi%2Fauth%2Fpipedrive%2Finstall',
                },
            });
        });
        await expect(
            callback(
                args(
                    req(
                        `/api/auth/pipedrive/callback?code=bound-code&state=${state}`,
                        cookie
                    )
                )
            )
        ).rejects.toMatchObject({ status: 302 });
        expect(fetchMock).not.toHaveBeenCalled();
    });

    it.each(['missing cookie', 'tampered state', 'expired state'])(
        'keeps shared state validation for %s',
        async (kind) => {
            const { state, cookie } = await flow();
            let value = state;
            if (kind === 'tampered state') value = 'invalid';
            if (kind === 'expired state')
                vi.spyOn(Date, 'now').mockReturnValue(Date.now() + 16 * 60_000);
            try {
                await expect(
                    callback(
                        args(
                            req(
                                `/api/auth/pipedrive/callback?code=bound-code&state=${value}`,
                                kind === 'missing cookie' ? undefined : cookie
                            )
                        )
                    )
                ).rejects.toMatchObject({ status: 400 });
                expect(fetchMock).not.toHaveBeenCalled();
            } finally {
                vi.restoreAllMocks();
            }
        }
    );

    it('renders a friendly stateless cancellation without reflecting provider text', async () => {
        const response = await callback(
            args(
                req(
                    '/api/auth/pipedrive/callback?error=user_denied&error_description=private-provider-data'
                )
            )
        );
        expect(await response.json()).toEqual({
            success: false,
            mode: 'install',
            error: 'Pipedrive installation was cancelled. No connection was saved.',
        });
        expect(fetchMock).not.toHaveBeenCalled();
    });

    it.each(['rejected', 'network failure', 'malformed success'])(
        'does not claim connection success on %s',
        async (kind) => {
            const { state, cookie } = await flow();
            if (kind === 'rejected')
                fetchMock.mockResolvedValue(
                    Response.json(
                        { detail: 'private provider response' },
                        { status: 409 }
                    )
                );
            if (kind === 'network failure')
                fetchMock.mockRejectedValue(new Error('private request data'));
            if (kind === 'malformed success')
                fetchMock.mockResolvedValue(Response.json({ success: true }));
            const response = await callback(
                args(
                    req(
                        `/api/auth/pipedrive/callback?code=bound-code&state=${state}`,
                        cookie
                    )
                )
            );
            const data = await response.json();
            expect(data).toMatchObject({ success: false, mode: 'install' });
            expect(JSON.stringify(data)).not.toMatch(/bound-code|private/);
            expect(response.headers.get('Set-Cookie')).toContain(
                'rotated-session'
            );
        }
    );

    it('preserves the editor popup callback without a server-side install exchange', async () => {
        const { state, cookie } = await flow('popup');
        const response = await callback(
            args(
                req(
                    `/api/auth/pipedrive/callback?code=popup-code&state=${state}`,
                    cookie
                )
            )
        );
        expect(await response.json()).toEqual({
            success: true,
            code: 'popup-code',
            redirectUri: `${origin}/api/auth/pipedrive/callback`,
            scopes: [],
        });
        expect(auth.requireAuth).not.toHaveBeenCalled();
        expect(fetchMock).not.toHaveBeenCalled();
    });
});
