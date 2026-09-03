// The Microsoft "Need admin approval" wall: an admin approves NoClick for the whole
// tenant through Entra's admin-consent endpoint, then the popup continues into the
// normal sign-in (admin consent returns no code). Pins the authorize branch, the
// success chain, the refused-consent copy, and the rewrite of the user-flow error.
// State sealing/binding is the oauthFlow.server test's job and is mocked out here.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('~/lib/oauthFlow.server', () => ({
    oauthRedirect: vi.fn((_req: Request, url: string) => ({ redirectedTo: url })),
    oauthCallbackUrl: vi.fn(async (req: Request) => new URL(req.url)),
}));
vi.mock('~/lib/oauthSetupPage.server', () => ({
    oauthNotConfiguredResponse: vi.fn(() => new Response('not configured', { status: 500 })),
}));
vi.mock('~/lib/instanceOAuth.server', () => ({
    applyInstanceOAuthEnv: vi.fn(async () => {}),
}));

import { loader as authorize } from '~/routes/api/auth/microsoft.authorize';
import { loader as callback } from '~/routes/api/auth/microsoft.callback';

const CLIENT_ID = 'client-123';
const REDIRECT_URI = 'https://app.example.com/api/auth/microsoft/callback';
const EXCEL_SCOPES = [
    'https://graph.microsoft.com/Files.ReadWrite.All',
    'https://graph.microsoft.com/User.Read',
];
const NAME = 'Excel OAuth - 9/3/2026';

function decodeState(url: URL): Record<string, unknown> {
    return JSON.parse(Buffer.from(url.searchParams.get('state')!, 'base64url').toString('utf8'));
}

async function runAuthorize(query: string): Promise<URL> {
    const res = (await authorize({
        request: new Request(`https://app.example.com/api/auth/microsoft/authorize?${query}`),
        params: {},
        context: {},
    } as never)) as unknown as { redirectedTo: string };
    return new URL(res.redirectedTo);
}

function rawState(extra: Record<string, unknown> = {}): string {
    return Buffer.from(
        JSON.stringify({ credentialName: NAME, scopes: EXCEL_SCOPES, nonce: 'n', timestamp: Date.now(), ...extra })
    ).toString('base64url');
}

function runCallback(query: string) {
    return callback({
        request: new Request(`https://app.example.com/api/auth/microsoft/callback?${query}`),
        params: {},
        context: {},
    } as never);
}

describe('Microsoft organization-wide admin consent', () => {
    const previous = { id: process.env.MICROSOFT_CLIENT_ID, uri: process.env.MICROSOFT_REDIRECT_URI };

    beforeEach(() => {
        process.env.MICROSOFT_CLIENT_ID = CLIENT_ID;
        process.env.MICROSOFT_REDIRECT_URI = REDIRECT_URI;
    });

    afterEach(() => {
        if (previous.id === undefined) delete process.env.MICROSOFT_CLIENT_ID;
        else process.env.MICROSOFT_CLIENT_ID = previous.id;
        if (previous.uri === undefined) delete process.env.MICROSOFT_REDIRECT_URI;
        else process.env.MICROSOFT_REDIRECT_URI = previous.uri;
    });

    it('the user sign-in still goes to the common authorize endpoint', async () => {
        const url = await runAuthorize(`name=${encodeURIComponent(NAME)}&scopes=${encodeURIComponent(EXCEL_SCOPES.join(','))}`);
        expect(url.host).toBe('login.microsoftonline.com');
        expect(url.pathname).toBe('/common/oauth2/v2.0/authorize');
        expect(url.searchParams.get('response_type')).toBe('code');
        expect(url.searchParams.get('prompt')).toBe('consent');
        expect(decodeState(url).adminConsent).toBe(false);
    });

    it('admin_consent=1 goes to the organizations admin-consent endpoint with the same scopes', async () => {
        const url = await runAuthorize(
            `name=${encodeURIComponent(NAME)}&scopes=${encodeURIComponent(EXCEL_SCOPES.join(','))}&admin_consent=1`
        );
        expect(url.host).toBe('login.microsoftonline.com');
        expect(url.pathname).toBe('/organizations/v2.0/adminconsent');
        expect(url.searchParams.get('client_id')).toBe(CLIENT_ID);
        expect(url.searchParams.get('redirect_uri')).toBe(REDIRECT_URI);
        const scope = url.searchParams.get('scope')!.split(' ');
        for (const s of EXCEL_SCOPES) expect(scope).toContain(s);
        expect(scope).toContain('offline_access');
        // Not an auth-code request: no response_type/prompt.
        expect(url.searchParams.has('response_type')).toBe(false);
        expect(url.searchParams.has('prompt')).toBe(false);
        const state = decodeState(url);
        expect(state.adminConsent).toBe(true);
        expect(state.credentialName).toBe(NAME);
        expect(state.scopes).toEqual(EXCEL_SCOPES);
    });

    it('a granted admin consent chains into the normal sign-in with the original name + scopes', async () => {
        const thrown = await runCallback(
            `admin_consent=True&tenant=aaaabbbb&scope=${encodeURIComponent(EXCEL_SCOPES.join(' '))}&state=${rawState({ adminConsent: true })}`
        ).then(() => null, (e: unknown) => e);
        expect(thrown).toBeInstanceOf(Response);
        const res = thrown as Response;
        expect(res.status).toBe(302);
        expect(res.headers.get('Cache-Control')).toBe('no-store');
        const next = new URL(res.headers.get('Location')!, 'https://app.example.com');
        expect(next.pathname).toBe('/api/auth/microsoft/authorize');
        expect(next.searchParams.get('name')).toBe(NAME);
        expect(next.searchParams.get('scopes')).toBe(EXCEL_SCOPES.join(','));
        expect(next.searchParams.has('admin_consent')).toBe(false);
    });

    it('a refused admin consent surfaces as an admin-approval error, not a sign-in error', async () => {
        const data = await runCallback(
            `admin_consent=True&error=access_denied&error_description=${encodeURIComponent(
                'AADSTS65004: The resource owner or authorization server denied the request.'
            )}&state=${rawState({ adminConsent: true })}`
        );
        expect(data.success).toBe(false);
        expect(data.error).toMatch(/^Admin approval was not granted: AADSTS65004/);
    });

    it('a user turned away by the admin-approval wall is pointed at the org-consent button', async () => {
        const data = await runCallback(
            `error=access_denied&error_description=${encodeURIComponent(
                'AADSTS90094: The grant requires admin permission. Trace ID: x'
            )}&state=${rawState()}`
        );
        expect(data.success).toBe(false);
        expect(data.error).toContain('approve NoClick for your organization');
    });

    it('a user simply declining consent keeps the provider text', async () => {
        const data = await runCallback(
            `error=access_denied&error_subcode=cancel&error_description=${encodeURIComponent(
                'AADSTS65004: User declined to consent to access the app.'
            )}&state=${rawState()}`
        );
        expect(data.error).toMatch(/^AADSTS65004/);
    });

    it('the plain code exchange is untouched', async () => {
        const data = await runCallback(`code=abc&state=${rawState()}`);
        expect(data).toMatchObject({
            success: true,
            code: 'abc',
            redirectUri: REDIRECT_URI,
            credentialName: NAME,
            scopes: EXCEL_SCOPES,
        });
    });
});
