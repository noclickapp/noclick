// @vitest-environment jsdom
// @vitest-environment-options {"url": "https://noclick.com/dashboard"}
// A hosted session survives a move of the Supabase URL: the server and the
// browser clients both read the session from the pinned cookie, whatever
// address the project is reached at (authCookieName).
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('~/lib/edition', () => ({ isLocalEdition: () => false }));

const { createServerSupabaseClient } = await import('~/lib/supabase');
const { getSupabaseBrowserClient } = await import('~/lib/supabase-client');

const PROJECT_URL = 'https://abcdefghijklmnopqrst.supabase.co';
const URLS = ['https://api.example.test', PROJECT_URL, 'https://auth.example.test'];
const COOKIE = 'sb-api-auth-token';

function session() {
    const exp = Math.floor(Date.now() / 1000) + 3600;
    const b64 = (value: object) => Buffer.from(JSON.stringify(value)).toString('base64url');
    const user = {
        id: 'user-1', aud: 'authenticated', role: 'authenticated', email: 'person@example.test',
        app_metadata: {}, user_metadata: {}, created_at: '2026-01-01T00:00:00Z',
    };
    return {
        access_token: `${b64({ alg: 'HS256', typ: 'JWT' })}.${b64({ sub: user.id, exp, aud: 'authenticated', role: 'authenticated' })}.sig`,
        token_type: 'bearer',
        expires_in: 3600,
        expires_at: exp,
        refresh_token: 'refresh-1',
        user,
    };
}

// The library's own cookie encoding: base64url of the session JSON behind a prefix.
const encoded = (value: object) => `base64-${Buffer.from(JSON.stringify(value)).toString('base64url')}`;

afterEach(() => {
    vi.unstubAllEnvs();
    document.cookie = `${COOKIE}=; path=/; max-age=0`;
});

describe('the hosted session cookie', () => {
    it('is read by the server client at every Supabase URL', async () => {
        const signedIn = session();
        for (const url of URLS) {
            vi.stubEnv('SUPABASE_URL', url);
            vi.stubEnv('SUPABASE_ANON_KEY', 'anon-key');
            const request = new Request('https://noclick.com/dashboard', {
                headers: { Cookie: `other=1; ${COOKIE}=${encoded(signedIn)}` },
            });
            const { data } = await createServerSupabaseClient(request, new Headers()).auth.getSession();
            expect(data.session?.access_token, url).toBe(signedIn.access_token);
        }
    });

    it("is read by the browser client at the project's own address", async () => {
        // The library keeps one browser client per page, so this file builds exactly one, on the
        // address the app moves to first; the server test covers every URL.
        const signedIn = session();
        document.cookie = `${COOKIE}=${encoded(signedIn)}; path=/`;
        const client = getSupabaseBrowserClient({ SUPABASE_URL: PROJECT_URL, SUPABASE_ANON_KEY: 'anon-key' });
        await client.auth.stopAutoRefresh();
        const { data } = await client.auth.getSession();
        expect(data.session?.access_token).toBe(signedIn.access_token);
    });
});
