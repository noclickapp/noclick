// A sign-in the server starts finishes at the callback with the verifier the server stored in the
// browser's cookies, and leaves the session cookie behind. supabase-js (2.111 on) also keeps each
// flow's verifier in a slot cookie of its own plus an index of them; the callback names no flow,
// so the exchange clears only the shared copy and a flow's slot stays until sign-out, at most five
// of them. Real supabase-js and @supabase/ssr; only GoTrue's token endpoint is answered here.
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('~/lib/edition', () => ({ isLocalEdition: () => false }));

const SUPABASE_URL = 'https://abcdefghijklmnopqrst.supabase.co';
const SITE = 'https://noclick.com';
const COOKIE = 'sb-api-auth-token';

vi.stubEnv('SUPABASE_URL', SUPABASE_URL);
vi.stubEnv('SUPABASE_ANON_KEY', 'anon-key');

const { createServerSupabaseClient } = await import('~/lib/supabase');
const { loader } = await import('~/routes/auth/callback');

afterEach(() => {
    vi.unstubAllGlobals();
});

type Jar = Map<string, string>;

/** The browser's jar after a response's Set-Cookie headers. */
function apply(jar: Jar, headers: Headers): Jar {
    for (const line of headers.getSetCookie()) {
        const [pair, ...attrs] = line.split(';').map((s) => s.trim());
        const eq = pair.indexOf('=');
        const name = pair.slice(0, eq);
        if (attrs.some((a) => /^max-age=0$/i.test(a))) jar.delete(name);
        else jar.set(name, pair.slice(eq + 1));
    }
    return jar;
}

const cookieHeader = (jar: Jar) => [...jar].map(([k, v]) => `${k}=${v}`).join('; ');
const verifierCookies = (jar: Jar) => [...jar.keys()].filter((name) => name.endsWith('-code-verifier'));

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

/** Starts a Google sign-in as auth.server.ts does and returns the callback GoTrue would redirect to. */
async function startSignIn(jar: Jar, code: string): Promise<URL> {
    const headers = new Headers();
    const request = new Request(`${SITE}/auth/login`, { headers: { Cookie: cookieHeader(jar) } });
    const { data, error } = await createServerSupabaseClient(request, headers).auth.signInWithOAuth({
        provider: 'google',
        options: { redirectTo: `${SITE}/auth/callback?next=%2Fdashboard`, skipBrowserRedirect: true },
    });
    expect(error).toBeNull();
    apply(jar, headers);
    const callback = new URL(new URL(data.url!).searchParams.get('redirect_to')!);
    expect(callback.searchParams.has('sb_flow_id')).toBe(false);
    callback.searchParams.set('code', code);
    return callback;
}

async function finishSignIn(jar: Jar, callback: URL) {
    const verifiers: unknown[] = [];
    vi.stubGlobal('fetch', async (input: RequestInfo | URL, init?: RequestInit) => {
        expect(String(input)).toBe(`${SUPABASE_URL}/auth/v1/token?grant_type=pkce`);
        verifiers.push(JSON.parse(String(init?.body)).code_verifier);
        return new Response(JSON.stringify(session()), { status: 200, headers: { 'Content-Type': 'application/json' } });
    });
    const response = (await loader({
        request: new Request(callback, { headers: { Cookie: cookieHeader(jar) } }),
        params: {},
        context: {},
    } as Parameters<typeof loader>[0])) as Response;
    vi.unstubAllGlobals();
    apply(jar, response.headers);
    return { response, verifiers };
}

describe('the sign-in callback', () => {
    it('exchanges the code with the stored verifier and sets the session cookie', async () => {
        const jar: Jar = new Map();
        const callback = await startSignIn(jar, 'auth-code-1');
        expect(verifierCookies(jar).sort()).toEqual([
            `${COOKIE}-code-verifier`,
            expect.stringMatching(new RegExp(`^${COOKIE}-flow-[0-9a-f]{32}-code-verifier$`)),
            `${COOKIE}-flows-code-verifier`,
        ]);

        const { response, verifiers } = await finishSignIn(jar, callback);

        expect(response.status).toBe(302);
        expect(response.headers.get('Location')).toBe('/dashboard');
        expect(verifiers).toHaveLength(1);
        expect(verifiers[0]).toMatch(/^[\w-]{43,128}$/);
        expect(jar.has(COOKIE)).toBe(true);
        expect(jar.has(`${COOKIE}-code-verifier`)).toBe(false);
    });

    it('keeps at most five flows of verifier cookies however often someone signs in', async () => {
        const jar: Jar = new Map();
        for (let i = 0; i < 8; i++) {
            const { response } = await finishSignIn(jar, await startSignIn(jar, `auth-code-${i}`));
            expect(response.headers.get('Location')).toBe('/dashboard');
        }
        // Five flow slots and their index; the shared copy goes with each exchange.
        expect(verifierCookies(jar)).toHaveLength(6);
    });
});
