import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { oauthCallbackUrl, oauthRedirect } from '~/lib/oauthFlow.server';

const SESSION_SECRET = 'oauth-flow-test-secret-with-sufficient-entropy';

function cookieFrom(response: Response): string {
    const setCookie = response.headers.get('Set-Cookie');
    if (!setCookie) throw new Error('missing binding cookie');
    return setCookie.split(';', 1)[0];
}

function stateFrom(response: Response): string {
    const location = response.headers.get('Location');
    if (!location) throw new Error('missing provider redirect');
    const state = new URL(location).searchParams.get('state');
    if (!state) throw new Error('missing protected state');
    return state;
}

describe('OAuth flow binding', () => {
    const previousSecret = process.env.SESSION_SECRET;

    beforeEach(() => {
        process.env.SESSION_SECRET = SESSION_SECRET;
    });

    afterEach(() => {
        if (previousSecret === undefined) delete process.env.SESSION_SECRET;
        else process.env.SESSION_SECRET = previousSecret;
    });

    it('encrypts provider state and restores it only for the bound browser', async () => {
        const rawState = Buffer.from(
            JSON.stringify({
                codeVerifier: 'private-verifier',
                scopes: ['read'],
            })
        ).toString('base64url');
        const response = await oauthRedirect(
            new Request('https://app.example.com/api/auth/example/authorize'),
            `https://provider.example/authorize?state=${rawState}`
        );
        const protectedState = stateFrom(response);

        expect(protectedState).not.toContain(rawState);
        expect(protectedState).not.toContain('private-verifier');
        expect(response.headers.get('Cache-Control')).toBe('no-store');
        expect(response.headers.get('Referrer-Policy')).toBe('no-referrer');

        const callback = new Request(
            `https://app.example.com/api/auth/example/callback?code=abc&state=${protectedState}`,
            { headers: { Cookie: cookieFrom(response) } }
        );
        const restored = await oauthCallbackUrl(callback);
        expect(restored.searchParams.get('state')).toBe(rawState);
    });

    it('rejects a callback without the browser binding', async () => {
        const response = await oauthRedirect(
            new Request('https://app.example.com/api/auth/example/authorize'),
            'https://provider.example/authorize?state=opaque'
        );
        const callback = new Request(
            `https://app.example.com/api/auth/example/callback?code=abc&state=${stateFrom(response)}`
        );
        await expect(oauthCallbackUrl(callback)).rejects.toMatchObject({
            status: 400,
        });
    });

    it('rejects tampered encrypted state', async () => {
        const response = await oauthRedirect(
            new Request('https://app.example.com/api/auth/example/authorize'),
            'https://provider.example/authorize?state=opaque'
        );
        const state = stateFrom(response);
        const tampered = `${state.slice(0, -1)}${state.endsWith('a') ? 'b' : 'a'}`;
        const callback = new Request(
            `https://app.example.com/api/auth/example/callback?code=abc&state=${tampered}`,
            { headers: { Cookie: cookieFrom(response) } }
        );
        await expect(oauthCallbackUrl(callback)).rejects.toMatchObject({
            status: 400,
        });
    });

    it('keeps several simultaneous provider flows valid', async () => {
        const authorize = new Request(
            'https://app.example.com/api/auth/example/authorize'
        );
        const first = await oauthRedirect(
            authorize,
            'https://provider.example/authorize?state=first'
        );
        const second = await oauthRedirect(
            new Request(authorize, { headers: { Cookie: cookieFrom(first) } }),
            'https://provider.example/authorize?state=second'
        );

        for (const [response, expected] of [
            [first, 'first'],
            [second, 'second'],
        ] as const) {
            const callback = new Request(
                `https://app.example.com/api/auth/example/callback?code=abc&state=${stateFrom(response)}`,
                { headers: { Cookie: cookieFrom(second) } }
            );
            expect(
                (await oauthCallbackUrl(callback)).searchParams.get('state')
            ).toBe(expected);
        }
    });

    it('keeps protected X state below the provider limit', async () => {
        const representative = Buffer.from(
            JSON.stringify({
                credentialName: 'Twitter',
                nonce: crypto.randomUUID(),
                timestamp: Date.now(),
                codeVerifier: crypto.randomUUID().repeat(2),
            })
        ).toString('base64url');
        const response = await oauthRedirect(
            new Request('https://app.example.com/api/auth/x/authorize'),
            `https://x.com/i/oauth2/authorize?state=${representative}`
        );
        expect(stateFrom(response).length).toBeLessThanOrEqual(500);
    });
});
