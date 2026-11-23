// The app's server end to end, through React Router's own request handler: the setup page, sign-in, the gate (the
// root's middleware and the server entry), the security headers, and the key proxy against a fake NoClick API.
// test/served.test.ts runs the built server itself.
import { Unauthenticated } from 'noclick';
import { inspect } from 'node:util';
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { readAccountStatus, toAccountStatus } from '@/screens/account/status';
import { BROWSER_BEARER, proxiedClient } from '@/sdk/proxied';
import { serverClient } from '@/server/client.server';
import type { AppConfig } from '@/server/config.server';
import { FORWARDED_REQUEST_HEADERS, PASSED_RESPONSE_HEADERS } from '@/server/proxy.server';
import { signInCookie } from '@/server/session.server';
import { WRONG_PASSWORD_DELAY_MS } from '@/server/signIn.server';
import { cookieOf, everything, NEEDED_HEADERS, ORIGIN_WIDE_HEADERS, startApp, startFakeApi, STATUS, type App, type FakeApi } from './harness';

const KEY = 'nk_test_fake';
const PASSWORD = 'violet harbor lantern 42';
const SECRET = 'a session secret that only these tests use';
const ORIGIN = 'http://localhost:3000';
const DAY_MS = 24 * 60 * 60 * 1000;
/** What the app's own SDK client sends with every call. */
const BEARER = { authorization: `Bearer ${BROWSER_BEARER}` };

let app: App;
let api: FakeApi;
/** Every response the tests read, as the browser got it, and everything the server wrote to the console. */
const transcript: string[] = [];
const consoleOutput: string[] = [];

beforeAll(async () => {
    for (const method of ['error', 'warn', 'log', 'info'] as const) {
        vi.spyOn(console, method).mockImplementation((...args: unknown[]) => {
            consoleOutput.push(args.map((arg) => (typeof arg === 'string' ? arg : inspect(arg, { depth: 5 }))).join(' '));
        });
    }
    [app, api] = await Promise.all([startApp(), startFakeApi()]);
}, 60_000);
afterAll(async () => {
    await Promise.all([app?.close(), api?.close()]);
});

function configure(overrides: Record<string, string> = {}) {
    const env = { NOCLICK_API_KEY: KEY, APP_PASSWORD: PASSWORD, SESSION_SECRET: SECRET, NOCLICK_API_URL: api.url, ...overrides };
    for (const [name, value] of Object.entries(env)) vi.stubEnv(name, value);
}
beforeEach(() => {
    configure();
    api.requests.length = 0;
    api.refused.clear();
});
afterEach(() => {
    vi.unstubAllEnvs();
});

const config = (): AppConfig => ({ password: PASSWORD, sessionSecret: SECRET, apiUrl: api.url, keyGiven: false });

/** What a page of the app's own sends with a POST: the browser names the page's origin. */
const SAME_ORIGIN = { origin: ORIGIN, 'sec-fetch-site': 'same-origin' };

async function send(path: string, init: RequestInit = {}, origin = ORIGIN): Promise<Response> {
    return app.handle(new Request(origin + path, init));
}

/** Reads a response whole, and keeps it in the transcript. */
async function read(response: Response) {
    const text = await everything(response.clone());
    transcript.push(text);
    return { status: response.status, headers: response.headers, body: await response.text() };
}

function signInRequest(password: string, next?: string, headers: Record<string, string> = SAME_ORIGIN): RequestInit {
    const form = new URLSearchParams({ password });
    if (next !== undefined) form.set('next', next);
    return { method: 'POST', body: form, headers };
}

async function signIn(origin = ORIGIN): Promise<string> {
    const response = await send('/login', signInRequest(PASSWORD), origin);
    expect(response.status).toBe(302);
    return cookieOf(response);
}

/** A cookie for a session signed in at `at` (ms since 1970), with `overrides` to the config it is signed for. */
async function cookieSignedAt(at: number, overrides: Partial<AppConfig> = {}): Promise<string> {
    const header = await signInCookie(new Request(`${ORIGIN}/`), { ...config(), ...overrides }, at);
    return cookieOf(new Response(null, { headers: { 'set-cookie': header } }));
}

/** The headers every answer of the app's carries, error pages and refusals included. */
function expectSecurityHeaders(headers: Headers, what: string) {
    expect(headers.get('x-frame-options'), what).toBe('DENY');
    expect(headers.get('content-security-policy'), what).toContain("frame-ancestors 'none'");
    expect(headers.get('x-content-type-options'), what).toBe('nosniff');
    expect(headers.get('cache-control'), what).toContain('no-store');
}

/** Requests React Router answers without running its middleware (a method no route takes, a path no route matches);
 *  the server entry gates them. */
const BEFORE_MIDDLEWARE: Array<[string, string]> = [
    ['OPTIONS', '/'],
    ['PROPFIND', '/'],
    ['OPTIONS', '/login'],
    ['GET', '/anything%0a'],
    ['GET', '/api/v1/status%0d'],
];

describe('before every setting is usable', () => {
    const SETUPS: Array<[string, Record<string, string>, string]> = [
        ['the key is missing', { NOCLICK_API_KEY: '' }, 'NOCLICK_API_KEY'],
        ['the key has a line break', { NOCLICK_API_KEY: 'nk_test_first\nnk_test_second' }, 'NOCLICK_API_KEY'],
        ['the key ends in a Windows line ending', { NOCLICK_API_KEY: 'nk_test_carriage\r' }, 'NOCLICK_API_KEY'],
        ['the key has a space', { NOCLICK_API_KEY: 'nk_test_with space' }, 'NOCLICK_API_KEY'],
        ['the password is missing', { APP_PASSWORD: '' }, 'APP_PASSWORD'],
        ['the password is short', { APP_PASSWORD: 'tulip-87' }, 'APP_PASSWORD'],
        ['the session secret is missing', { SESSION_SECRET: '' }, 'SESSION_SECRET'],
        ['the session secret is short', { SESSION_SECRET: 'W'.repeat(31) }, 'SESSION_SECRET'],
        ['the API address is plain http to another machine', { NOCLICK_API_URL: 'http://api.example.com' }, 'NOCLICK_API_URL'],
        ['the API address is not an address', { NOCLICK_API_URL: 'api dot example' }, 'NOCLICK_API_URL'],
    ];
    // Pages: the setup page, drawn in the app's own look.
    const PAGES: Array<[string, () => RequestInit]> = [
        ['/', () => ({})],
        ['/login', () => ({})],
        ['/account?x=1', () => ({})],
        ['/no/such/page', () => ({})],
        ['/login', () => signInRequest(PASSWORD)],
    ];
    // What React Router answers without middleware (the server entry's gate): the same 503 and names, as text.
    const UNSEEN = BEFORE_MIDDLEWARE.filter(([, path]) => !path.startsWith('/api'));
    const API: Array<[string, () => RequestInit]> = [
        ['/api/v1/account', () => ({ headers: BEARER })],
        ['/api/v1/status%0d', () => ({})],
        ['/api/v1/echo', () => ({ method: 'POST', body: '{}', headers: { ...SAME_ORIGIN, ...BEARER, 'content-type': 'application/json' } })],
    ];

    it.each(SETUPS)('when %s, every path answers the setup page (503), naming it and no value', async (_, overrides, name) => {
        const cookie = await signIn();
        const logged = consoleOutput.length;
        configure(overrides);
        const values = [KEY, PASSWORD, SECRET, ...Object.values(overrides).filter((value) => value.length > 3)];
        const noValueIn = (text: string, what: string) => {
            for (const value of values) expect(text.includes(value), `${what} holds a value`).toBe(false);
        };
        const answer = async (method: string | undefined, path: string, init: RequestInit = {}) => {
            const what = `${method ?? 'GET'} ${path}`;
            const response = await read(await send(path, { ...init, method, headers: { ...(init.headers as Record<string, string>), cookie } }));
            expect(response.status, what).toBe(503);
            expect(response.body, what).toContain(name);
            expectSecurityHeaders(response.headers, what);
            noValueIn(response.body, what);
            return response;
        };
        for (const [path, init] of PAGES) {
            const request = init();
            const page = await answer(request.method, path, request);
            expect(page.headers.get('content-type'), path).toContain('text/html');
            expect(page.body, path).toContain('Finish setting up this app');
        }
        for (const [method, path] of UNSEEN) {
            const text = await answer(method, path);
            expect(text.body, `${method} ${path}`).toContain('This app isn’t set up yet');
        }
        for (const [path, init] of API) {
            const response = await answer(init().method, path, init());
            expect(JSON.parse(response.body).error.missing, path).toEqual([name]);
        }
        // A page's data request: the same setup data, which the open page draws.
        const data = await read(await send('/_root.data', { headers: { cookie } }));
        expect(data.status).toBe(503);
        expect(data.body).toContain(name);
        noValueIn(data.body, 'GET /_root.data');
        expect(api.requests).toEqual([]);
        noValueIn(consoleOutput.slice(logged).join('\n'), 'the console');
    });

    it('names every unusable setting at once', async () => {
        configure({ NOCLICK_API_KEY: '', APP_PASSWORD: '', SESSION_SECRET: '' });
        const { body } = await read(await send('/api/v1/status'));
        expect(JSON.parse(body).error.missing).toEqual(['NOCLICK_API_KEY', 'APP_PASSWORD', 'SESSION_SECRET']);
    });

    it('answers HEAD with the setup page’s status and no body', async () => {
        configure({ SESSION_SECRET: '' });
        const response = await read(await send('/', { method: 'HEAD' }));
        expect(response.status).toBe(503);
        expect(response.body).toBe('');
    });
});

describe('a copy deployed on NoClick, which gives it its key', () => {
    // The bearer NoClick's app hosting gives a production release; nobody sets or pastes it.
    const GIVEN = 'nk_app_release.bearer';
    const WAITING = {
        reason: 'account_key_waiting',
        message: 'This app’s key to the account waits for the account’s owner to approve it.',
        next_step: 'The owner approves it from the link NoClick sent them, or signed in to NoClick; it works at once after.',
    };

    it('says it waits for its owner’s yes in place of every page, then opens with no new release', async () => {
        const clock = vi.spyOn(Date, 'now');
        const started = 1_800_000_000_000;
        clock.mockReturnValue(started);
        configure({ NOCLICK_API_KEY: GIVEN });
        api.refused.set(GIVEN, WAITING);

        const page = await read(await send('/'));
        expect(page.status).toBe(503);
        expect(page.body).toContain('This app’s key isn’t ready');
        expect(page.body).toContain('waits for the account’s owner to approve it');
        expect(page.body).toContain('There is nothing to paste');
        // Nothing asks the reader to set a variable, and the key itself is nowhere.
        expect(page.body).not.toContain('Finish setting up this app');
        expect(page.body).not.toContain('.env.example');
        expect(page.body).not.toContain(GIVEN);
        const proxied = await read(await send('/api/v1/status', { headers: BEARER }));
        expect(proxied.status).toBe(503);
        expect(JSON.parse(proxied.body).error).toMatchObject({ missing: ['NOCLICK_API_KEY'], next_step: expect.stringContaining('approves it from the link') });
        // One question to the API answers every request for a few seconds.
        expect(api.requests.filter((request) => request.url === '/v1/status')).toHaveLength(1);
        expect(api.requests[0].headers.authorization).toBe(`Bearer ${GIVEN}`);

        // The owner approves: the same release, the same bearer, and the next look finds it works.
        api.refused.clear();
        clock.mockReturnValue(started + 6_000);
        const opened = await send('/');
        expect(opened.status).toBe(302);
        expect(opened.headers.get('location')).toBe('/login');
        const cookie = await signIn();
        const status = await read(await send('/api/v1/status', { headers: { ...BEARER, cookie } }));
        expect(status.status).toBe(200);
        expect(api.requests.at(-1)?.headers.authorization).toBe(`Bearer ${GIVEN}`);
        clock.mockRestore();
    });

    it('goes on when the API can’t be asked, and leaves a key somebody set alone', async () => {
        // A key somebody created and set: the app never asks where it stands.
        expect((await send('/')).status).toBe(302);
        expect(api.requests).toEqual([]);
        // A given key whose standing can't be read: nothing is known, so the app opens and says so in its log.
        const logged = consoleOutput.length;
        configure({ NOCLICK_API_KEY: 'nk_app_other.bearer', NOCLICK_API_URL: 'http://127.0.0.1:9' });
        expect((await send('/')).status).toBe(302);
        const said = consoleOutput.slice(logged).join('\n');
        expect(said).toContain('couldn\'t ask NoClick\'s API whether the key NoClick gave it works yet');
        expect(said).not.toContain('nk_app_other');
    });

    it('says a release NoClick gave no key has none, with nothing to paste', async () => {
        configure({ NOCLICK_API_KEY: '', NOCLICK_PROJECT_ID: 'prj_1', NOCLICK_DEPLOYMENT_TOKEN: 'nk_dep_preview' });
        const page = await read(await send('/'));
        expect(page.status).toBe(503);
        expect(page.body).toContain('This app’s key isn’t ready');
        expect(page.body).toContain('this release has none');
        expect(page.body).not.toContain('developer console');
        expect(page.body).not.toContain('nk_dep_preview');
    });
});

describe('the gate', () => {
    it('sees, without a session, the requests React Router answers without its middleware', async () => {
        const answers = await Promise.all(BEFORE_MIDDLEWARE.map(([method, path]) => send(path, { method }).then(read)));
        const seen = Object.fromEntries(BEFORE_MIDDLEWARE.map(([method, path], i) => [`${method} ${path}`, answers[i]]));
        expect(seen['OPTIONS /'].status).toBe(302);
        expect(seen['OPTIONS /'].headers.get('location')).toBe('/login');
        expect(seen['PROPFIND /'].headers.get('location')).toBe('/login');
        // The sign-in page is open: React Router's own refusal of the method.
        expect(seen['OPTIONS /login'].status).toBe(405);
        expect(seen['GET /anything%0a'].headers.get('location')).toMatch(/^\/login\?next=%2Fanything%250a$/i);
        expect(seen['GET /api/v1/status%0d'].status).toBe(401);
        for (const [what, answer] of Object.entries(seen)) expectSecurityHeaders(answer.headers, what);
    });

    it('sends a page’s data request to sign in, keeping the page, whether or not a route matched it', async () => {
        const routed = await read(await send('/account.data?x=1&_routes=routes%2FnotFound'));
        expect(routed.status).toBe(202);
        expect(routed.body).toContain('"/login?next=%2Faccount%3Fx%3D1"');
        expect((await read(await send('/_root.data'))).body).toContain('"/login"');
        // No route matches this one: the server entry's gate, which also asks for a fresh document.
        const unrouted = await read(await send('/anything%0a.data'));
        expect(unrouted.status).toBe(202);
        expect(unrouted.body).toMatch(/"\/login\?next=%2Fanything%250a"/i);
        expect(unrouted.body).toContain('"reload",true');
        expectSecurityHeaders(unrouted.headers, 'GET /anything%0a.data');
    });

    it('leaves React Router’s route manifest to it, the one answer it gives before any of the app’s code', async () => {
        const manifest = await send('/__manifest?paths=%2F&version=another');
        // Another version than the app's: React Router asks for a fresh document, telling nothing.
        expect(manifest.status).toBe(204);
        expect(manifest.headers.get('x-frame-options')).toBeNull();
    });

    it('opens /login and its data request only, not paths that merely start with it', async () => {
        expect((await send('/login')).status).toBe(200);
        expect((await send('/login.data')).status).toBe(200);
        for (const path of ['/login/x', '/loginx', '/login.data/x', '/LOGIN']) {
            expect((await send(path)).headers.get('location'), path).toMatch(/^\/login(\?|$)/);
        }
    });

    it('lets React Router answer a signed-in owner’s other requests, with the security headers', async () => {
        const cookie = await signIn();
        const options = await read(await send('/', { method: 'OPTIONS', headers: { cookie } }));
        expect(options.status).toBe(405);
        expectSecurityHeaders(options.headers, 'OPTIONS /');
        const missing = await read(await send('/no/such/page', { headers: { cookie } }));
        expect(missing.status).toBe(404);
        expect(missing.body).toContain('Page not found');
        expectSecurityHeaders(missing.headers, '404');
        const unrouted = await read(await send('/anything%0a', { headers: { cookie } }));
        expect(unrouted.status).toBe(404);
        expectSecurityHeaders(unrouted.headers, 'GET /anything%0a');
    });
});

describe('signing in', () => {
    it('sends a page without a session to sign in, keeping where it was going', async () => {
        expect((await send('/account?x=1')).headers.get('location')).toBe('/login?next=%2Faccount%3Fx%3D1');
        expect((await send('/')).headers.get('location')).toBe('/login');
        expect((await send('/no/such/page')).headers.get('location')).toBe('/login?next=%2Fno%2Fsuch%2Fpage');
        const login = await read(await send('/login'));
        expect(login.status).toBe(200);
        expect(login.body).toContain('Sign in');
    });

    it('refuses a wrong password after the delay, with no cookie', async () => {
        const started = Date.now();
        const response = await read(await send('/login', signInRequest('violet harbor lantern 43')));
        expect(Date.now() - started).toBeGreaterThanOrEqual(WRONG_PASSWORD_DELAY_MS - 50);
        expect(response.status).toBe(401);
        expect(response.headers.get('set-cookie')).toBeNull();
        expect(response.body).toContain('That password isn’t right.');
    });

    it('signs in with the right password: an HttpOnly, SameSite=Lax cookie for the whole site, for 7 days', async () => {
        const response = await send('/login', signInRequest(PASSWORD));
        expect(response.status).toBe(302);
        expect(response.headers.get('location')).toBe('/');
        const cookie = response.headers.get('set-cookie')!;
        expect(cookie).toMatch(/^noclick-app-session=[^;]+; Max-Age=604800; Path=\/; HttpOnly; SameSite=Lax$/);
        // On this machine over http, the browser wouldn't keep a Secure cookie.
        expect(cookie).not.toContain('Secure');

        const home = await read(await send('/', { headers: { cookie: cookieOf(response) } }));
        expect(home.status).toBe(200);
        expect(home.body).toContain('Reading your NoClick account');
        expectSecurityHeaders(home.headers, 'the account page');
        expect((await send('/login?next=%2Faccount', { headers: { cookie: cookieOf(response) } })).headers.get('location')).toBe('/account');
    });

    it('makes the cookie Secure and __Host- anywhere but a browser on this machine, and asks for https only', async () => {
        for (const [origin, headers] of [
            ['https://app.example', SAME_ORIGIN],
            [ORIGIN, { ...SAME_ORIGIN, 'x-forwarded-for': '203.0.113.9' }],
        ] as const) {
            const response = await send('/login', signInRequest(PASSWORD, undefined, { ...headers, origin }), origin);
            const cookie = response.headers.get('set-cookie')!;
            expect(cookie).toMatch(/^__Host-noclick-app-session=[^;]+; Max-Age=604800; Path=\/; HttpOnly; Secure; SameSite=Lax$/);
            expect(response.headers.get('strict-transport-security')).toBe('max-age=31536000');
            const home = await send('/', { headers: { ...headers, cookie: cookieOf(response) } }, origin);
            expect(home.status).toBe(200);
            expect(home.headers.get('strict-transport-security')).toBe('max-age=31536000');
        }
        // Served on this machine, plain http stays usable.
        expect((await send('/login')).headers.get('strict-transport-security')).toBeNull();
    });

    // Paths a browser reads as another site once their dot segments are resolved, or outright.
    const OFF_SITE = [
        'https://evil.example',
        '//evil.example',
        '/\\evil.example',
        '/\t/evil.example',
        '/.//evil.example/phish',
        '/..//evil.example',
        '/a/..//evil.example',
        '/%2e//evil.example',
        '/login/..//evil.example',
        '/.//user:pw@evil.example',
    ];

    it.each([['/account?x=1', '/account?x=1'], ['/agents/agt_1#latest', '/agents/agt_1#latest'], ['/login', '/'], ['', '/'], ...OFF_SITE.map((next) => [next, '/'])])(
        'after signing in, goes to next=%j as %j',
        async (next, expected) => {
            const response = await send('/login', signInRequest(PASSWORD, next));
            expect(response.status).toBe(302);
            expect(response.headers.get('location')).toBe(expected);
        },
    );

    it('keeps a signed-in owner on this site when /login names another next, as a page and as a data request', async () => {
        const cookie = await signIn();
        for (const next of OFF_SITE) {
            const page = await send(`/login?next=${encodeURIComponent(next)}`, { headers: { cookie } });
            expect(page.status, next).toBe(302);
            expect(page.headers.get('location'), next).toBe('/');
            const data = await read(await send(`/login.data?next=${encodeURIComponent(next)}`, { headers: { cookie } }));
            expect(data.body, next).toContain('"redirect","/"');
            expect(data.body, next).not.toContain('evil.example');
        }
        expect((await send('/login?next=%2Faccount%3Fx%3D1', { headers: { cookie } })).headers.get('location')).toBe('/account?x=1');
    });

    it('counts a tampered, expired, future or otherwise-signed cookie as no session', async () => {
        const valid = await signIn();
        const [name, value] = valid.split('=');
        const tampered = `${name}=${value.slice(0, 5)}${value[5] === 'A' ? 'B' : 'A'}${value.slice(6)}`;
        const cookies = {
            tampered,
            expired: await cookieSignedAt(Date.now() - 7 * DAY_MS - 1000),
            future: await cookieSignedAt(Date.now() + 60 * 60 * 1000),
            'another secret': await cookieSignedAt(Date.now(), { sessionSecret: 'Z'.repeat(40) }),
        };
        for (const [kind, cookie] of Object.entries(cookies)) {
            const page = await send('/', { headers: { cookie } });
            expect(page.status, kind).toBe(302);
            expect(page.headers.get('location'), kind).toBe('/login');
            expect((await send('/api/v1/status', { headers: { cookie, ...BEARER } })).status, kind).toBe(401);
        }
        // Six days and 23 hours old is still a session.
        expect((await send('/', { headers: { cookie: await cookieSignedAt(Date.now() - 7 * DAY_MS + 60 * 60 * 1000) } })).status).toBe(200);
        expect(api.requests).toEqual([]);
    });

    it('ends every session when the password changes', async () => {
        const cookie = await signIn();
        configure({ APP_PASSWORD: 'a-new-password-for-the-app' });
        expect((await send('/', { headers: { cookie } })).headers.get('location')).toBe('/login');
    });

    it('signs out with a POST that clears the cookie; a GET does nothing', async () => {
        const cookie = await signIn();
        expect((await send('/logout', { headers: { cookie } })).status).toBe(405);
        const response = await send('/logout', { method: 'POST', headers: { ...SAME_ORIGIN, cookie } });
        expect(response.status).toBe(302);
        expect(response.headers.get('location')).toBe('/login');
        expect(response.headers.get('set-cookie')).toBe('noclick-app-session=; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT; HttpOnly; SameSite=Lax');
    });

    it('signs in from the page’s script too (a data request), with the same cookie', async () => {
        const response = await read(await send('/login.data', signInRequest(PASSWORD, '/account')));
        expect(response.status).toBe(202);
        expect(response.body).toContain('"/account"');
        expect(response.headers.get('set-cookie')).toMatch(/^noclick-app-session=[^;]+; Max-Age=604800; Path=\/; HttpOnly; SameSite=Lax$/);
    });

    it('turns away, unchecked, an attempt past the ones it is already checking, the right password too', async () => {
        const wrong = Array.from({ length: 3 }, (_, n) => send('/login', signInRequest(`not-the-password-${n}`)));
        // Long enough for those three to reach their delay, well short of its end.
        await new Promise((resolve) => setTimeout(resolve, WRONG_PASSWORD_DELAY_MS / 4));
        const busy = await read(await send('/login', signInRequest(PASSWORD)));
        expect(busy.status).toBe(429);
        expect(busy.headers.get('set-cookie')).toBeNull();
        expect((await Promise.all(wrong)).map((response) => response.status)).toEqual([401, 401, 401]);
        expect((await send('/login', signInRequest(PASSWORD))).status).toBe(302);
    });

    it('refuses a sign-in form too big to be one, unread', async () => {
        const response = await send('/login', signInRequest(`${PASSWORD}${'x'.repeat(20_000)}`));
        expect(response.status).toBe(400);
        expect(response.headers.get('set-cookie')).toBeNull();
    });
});

describe('requests from other sites', () => {
    // A page POST whose Origin names another host is refused by React Router itself (400) or the gate (403); the gate
    // alone guards the key proxy, a resource route React Router doesn't check.
    it.each([
        ['another site', { 'sec-fetch-site': 'cross-site', origin: 'https://evil.example' }],
        ['another site, naming only itself in Sec-Fetch-Site', { 'sec-fetch-site': 'cross-site' }],
        ['a sibling subdomain', { 'sec-fetch-site': 'same-site', origin: 'https://other.localhost' }],
        ['an older browser naming another origin', { origin: 'https://evil.example' }],
        ['an older browser on the app’s host over another scheme', { origin: 'https://localhost:3000' }],
        ['a sandboxed frame', { origin: 'null' }],
    ])('refuses a sign-in, a sign-out and every proxy call sent by %s', async (_, headers) => {
        const cookie = await signIn();
        const login = await send('/login', signInRequest(PASSWORD, undefined, headers));
        expect([400, 403]).toContain(login.status);
        // With no Origin, or one on the app's host, React Router's own check passes it: the gate alone refuses it.
        if (!('origin' in headers) || headers.origin.includes('localhost:3000')) expect(login.status).toBe(403);
        expect(login.headers.get('set-cookie')).toBeNull();
        const logout = await send('/logout', { method: 'POST', headers: { ...headers, cookie } });
        expect([400, 403]).toContain(logout.status);
        expect(logout.headers.get('set-cookie')).toBeNull();
        const write = await read(
            await send('/api/v1/echo', { method: 'POST', body: '{"x":1}', headers: { ...headers, ...BEARER, cookie, 'content-type': 'application/json' } }),
        );
        expect(write.status).toBe(403);
        expect(JSON.parse(write.body).error.type).toBe('permission_denied');
        // Even a read: the proxy answers this app's own pages only.
        expect((await send('/api/v1/status', { headers: { ...headers, ...BEARER, cookie } })).status).toBe(403);
        expect(api.requests).toEqual([]);
    });

    it('takes the scheme a proxy in front says the request came over as the app’s', async () => {
        // An older browser (no Sec-Fetch-Site) on an https page, behind a proxy that took the request over https.
        const behindTls = { origin: 'https://localhost:3000', 'x-forwarded-proto': 'https' };
        const cookie = cookieOf(await send('/login', signInRequest(PASSWORD, undefined, behindTls)));
        expect((await send('/api/v1/echo', { method: 'POST', body: '{}', headers: { ...behindTls, ...BEARER, cookie } })).status).toBe(200);
        expect(api.requests).toHaveLength(1);
        // The same page over plain http is another origin.
        const plain = { origin: 'http://localhost:3000', 'x-forwarded-proto': 'https', ...BEARER, cookie };
        expect((await send('/api/v1/echo', { method: 'POST', body: '{}', headers: plain })).status).toBe(403);
    });

    it('takes requests from the app’s own pages, ones the person started, and clients that aren’t browsers', async () => {
        const cookie = await signIn();
        for (const headers of [SAME_ORIGIN, { 'sec-fetch-site': 'none' }, {}] as Record<string, string>[]) {
            expect((await send('/api/v1/echo', { method: 'POST', body: '{}', headers: { ...headers, ...BEARER, cookie } })).status).toBe(200);
        }
        expect(api.requests).toHaveLength(3);
    });
});

describe('the key proxy', () => {
    it('answers 401 without a session, and never calls the API', async () => {
        for (const init of [{ headers: BEARER }, { method: 'POST', body: '{}', headers: { ...SAME_ORIGIN, ...BEARER } }]) {
            const response = await read(await send('/api/v1/status', init));
            expect(response.status).toBe(401);
            expect(JSON.parse(response.body).error).toMatchObject({ type: 'unauthenticated', reason: 'signed_out' });
        }
        expect(api.requests).toEqual([]);
    });

    it('refuses a signed-in call without the browser client’s bearer: a link, an embed, a page opened on its own', async () => {
        const cookie = await signIn();
        for (const headers of [{}, { authorization: 'Bearer something-else' }, { 'sec-fetch-site': 'none', 'sec-fetch-mode': 'navigate' }] as Record<string, string>[]) {
            const response = await read(await send('/api/v1/status', { headers: { ...headers, cookie } }));
            expect(response.status).toBe(403);
            expect(response.headers.get('content-type')).toContain('application/json');
            expect(JSON.parse(response.body).error.type).toBe('permission_denied');
        }
        // Through /login with the API as `next`: the redirect lands on a refusal, not on an answer with the key.
        const viaLogin = await send(`/login?next=${encodeURIComponent('/api/v1/status')}`, { headers: { cookie } });
        expect(viaLogin.headers.get('location')).toBe('/api/v1/status');
        expect((await send('/api/v1/status', { headers: { cookie } })).status).toBe(403);
        expect(api.requests).toEqual([]);
    });

    it('calls the API with the app’s key and only the request headers it allows', async () => {
        // As behind a proxy in front of the app, which adds its own headers (and so gets the Secure cookie).
        const behindProxy = { ...SAME_ORIGIN, 'x-forwarded-for': '203.0.113.9' };
        const cookie = cookieOf(await send('/login', signInRequest(PASSWORD, undefined, behindProxy)));
        expect(cookie).toMatch(/^__Host-/);
        const response = await read(
            await send('/api/v1/status?limit=2&cursor=abc', {
                headers: {
                    ...behindProxy,
                    ...BEARER,
                    cookie,
                    accept: 'application/json',
                    'idempotency-key': 'nc_0a1b2c',
                    'noclick-user': 'user_42',
                    'user-agent': 'ExampleBrowser/1.0',
                    referer: `${ORIGIN}/account`,
                    'x-extra': 'not for the API',
                },
            }),
        );
        expect(response.status).toBe(200);
        expect(JSON.parse(response.body)).toEqual(STATUS);

        const [upstream] = api.requests;
        expect(upstream.url).toBe('/v1/status?limit=2&cursor=abc');
        expect(upstream.headers.authorization).toBe(`Bearer ${KEY}`);
        expect(upstream.headers).toMatchObject({ accept: 'application/json', 'idempotency-key': 'nc_0a1b2c', 'noclick-user': 'user_42' });
        for (const name of ['cookie', 'origin', 'referer', 'x-forwarded-for', 'x-extra', 'sec-fetch-site']) expect(upstream.headers[name], name).toBeUndefined();
        expect(upstream.headers['user-agent']).not.toBe('ExampleBrowser/1.0');
        // Anything else the API saw is fetch's own (the connection, the encodings it reads).
        const fetchOwn = ['host', 'connection', 'accept-encoding', 'accept-language', 'sec-fetch-mode', 'user-agent', 'content-length', 'transfer-encoding'];
        const allowed = new Set<string>([...FORWARDED_REQUEST_HEADERS, 'authorization', ...fetchOwn]);
        expect(Object.keys(upstream.headers).filter((name) => !allowed.has(name))).toEqual([]);
    });

    it('passes back only the response headers it lists, and sets its own', async () => {
        const cookie = await signIn();
        const response = await read(await send('/api/v1/headers', { headers: { cookie, ...BEARER } }));
        expect(response.status).toBe(200);
        const passed = Object.fromEntries([...response.headers].filter(([name]) => !['content-type', 'cache-control', 'content-security-policy', 'x-content-type-options', 'cross-origin-resource-policy', 'x-frame-options', 'strict-transport-security'].includes(name)));
        expect(passed).toEqual(NEEDED_HEADERS);
        expect(Object.keys(NEEDED_HEADERS).every((name) => (PASSED_RESPONSE_HEADERS as readonly string[]).includes(name))).toBe(true);
        for (const name of [...Object.keys(ORIGIN_WIDE_HEADERS), 'x-echo-authorization', 'set-cookie']) expect(response.headers.get(name), name).toBeNull();
        expect(response.headers.get('cache-control')).toBe('no-store, no-transform');
        expect(response.headers.get('content-security-policy')).toBe("default-src 'none'; frame-ancestors 'none'; sandbox");
        expect(response.headers.get('x-content-type-options')).toBe('nosniff');
        expect(response.headers.get('cross-origin-resource-policy')).toBe('same-origin');
        expect(response.headers.get('x-frame-options')).toBe('DENY');
    });

    it('passes the method and body on, streamed as it arrives rather than read whole first', async () => {
        const cookie = await signIn();
        const encoder = new TextEncoder();
        let push!: ReadableStreamDefaultController<Uint8Array>;
        const body = new ReadableStream<Uint8Array>({ start: (controller) => void (push = controller) });
        push.enqueue(encoder.encode('{"part":"one",'));
        const firstChunk = api.firstChunkOfNextEcho();
        const pending = send('/api/v1/echo', {
            method: 'PATCH',
            body,
            headers: { ...SAME_ORIGIN, ...BEARER, cookie, 'content-type': 'application/json' },
            duplex: 'half',
        } as RequestInit);
        // The API has the first part while the rest hasn't been written: nothing waited for the whole body.
        await within(firstChunk, 5_000, 'the first part of the body never reached the API');
        push.enqueue(encoder.encode('"then":"two"}'));
        push.close();
        const response = await read(await pending);
        expect(JSON.parse(response.body)).toEqual({ received: '{"part":"one","then":"two"}' });
        expect(api.requests[0].method).toBe('PATCH');
        expect(api.requests[0].headers['content-type']).toBe('application/json');
    });

    it('streams events back as they come, not when the stream ends', async () => {
        const cookie = await signIn();
        const response = await send('/api/v1/stream', { headers: { cookie, ...BEARER, accept: 'text/event-stream' } });
        expect(response.status).toBe(200);
        expect(response.headers.get('content-type')).toBe('text/event-stream');
        const reader = response.body!.getReader();
        const decoder = new TextDecoder();
        const first = await within(reader.read(), 5_000, 'the first event waited for the stream to end');
        expect(decoder.decode(first.value)).toContain('{"n":1}');
        api.streams.at(-1)!.release();
        let rest = '';
        for (let chunk = await reader.read(); !chunk.done; chunk = await reader.read()) rest += decoder.decode(chunk.value);
        expect(rest).toContain('{"n":2}');
        transcript.push(decoder.decode(first.value) + rest);
    });

    it('stops the API call when the browser goes away', async () => {
        const cookie = await signIn();
        const browser = new AbortController();
        const response = await send('/api/v1/stream', { headers: { cookie, ...BEARER }, signal: browser.signal });
        expect(response.status).toBe(200);
        const stream = api.streams.at(-1)!;
        browser.abort();
        await within(stream.goneEarly, 3_000, 'the call to the API went on after the browser went away');
    });

    it('hands back a compressed body decoded, a redirect as the app’s path and an empty answer as empty', async () => {
        const cookie = await signIn();
        const gzipped = await read(await send('/api/v1/gzipped', { headers: { cookie, ...BEARER } }));
        expect(JSON.parse(gzipped.body)).toEqual({ compressed: true });
        expect(gzipped.headers.get('content-encoding')).toBeNull();
        const moved = await read(await send('/api/v1/moved', { headers: { cookie, ...BEARER } }));
        expect(moved.status).toBe(307);
        expect(moved.headers.get('location')).toBe('/api/v1/status?from=moved');
        const nothing = await read(await send('/api/v1/nothing', { method: 'DELETE', headers: { cookie, ...BEARER } }));
        expect(nothing.status).toBe(204);
        expect(nothing.body).toBe('');
    });

    it.each([
        ['an encoded climb out of /v1', '/api/v1/agents/..%2f..%2fadmin', 400],
        ['an encoded dot segment', '/api/v1/%2e%2e%2fadmin', 400],
        ['an empty segment', '/api/v1//evil.example/v1/x', 400],
        ['an absolute address in the path', '/api/v1/https://evil.example/v1/x', 400],
        ['an encoded backslash', '/api/v1/agents%5c..%5cadmin', 400],
        ['an encoded control character', '/api/v1/agents%00', 400],
        ['bad percent-encoding', '/api/v1/agents%zz', 400],
        ['/v1 itself', '/api/v1/', 400],
        // A dot segment the URL already resolves leaves /api/v1 altogether: no proxy route takes it.
        ['a dot segment', '/api/v1/%2e%2e/admin', 404],
        ['a path outside /v1', '/api/v2/status', 404],
    ])('refuses %s, unforwarded', async (_, path, status) => {
        const cookie = await signIn();
        const response = await read(await send(path, { headers: { cookie, ...BEARER } }));
        expect(response.status).toBe(status);
        expect(api.requests).toEqual([]);
    });

    it('keeps an odd path that names another host on the API’s own host, as a path', async () => {
        const cookie = await signIn();
        for (const path of ['/api/v1/@evil.example/x', '/api/v1/https:%2f%2fevil.example%2fv1']) {
            expect((await send(path, { headers: { cookie, ...BEARER } })).status).toBe(404);
        }
        const host = new URL(api.url).host;
        expect(api.requests.map((request) => [request.headers.host, request.url])).toEqual([
            [host, '/v1/@evil.example/x'],
            [host, '/v1/https:%2f%2fevil.example%2fv1'],
        ]);
    });

    it('answers 502 in plain words when the API can’t be reached, logging no secret', async () => {
        const cookie = await signIn();
        const logged = consoleOutput.length;
        configure({ NOCLICK_API_URL: 'http://127.0.0.1:9' });
        const response = await read(await send('/api/v1/status', { headers: { cookie, ...BEARER } }));
        expect(response.status).toBe(502);
        expect(JSON.parse(response.body).error).toMatchObject({ type: 'upstream_error', message: 'This app’s server couldn’t reach NoClick’s API.' });
        const said = consoleOutput.slice(logged).join('\n');
        expect(said).toContain('couldn\'t reach NoClick\'s API at http://127.0.0.1:9');
        for (const secret of [KEY, PASSWORD, SECRET]) expect(said.includes(secret)).toBe(false);
    });
});

describe('the SDK, through the session and the proxy', () => {
    const throughTheApp = (cookie?: string) =>
        proxiedClient(ORIGIN, {
            maxRetries: 0,
            fetch: (input, init) => {
                const request = new Request(input, init);
                if (cookie) request.headers.set('cookie', cookie);
                return app.handle(request);
            },
        });

    it('reads the account, with the app’s key reaching the API and the browser’s bearer not', async () => {
        const cookie = await signIn();
        expect(await readAccountStatus(throughTheApp(cookie))).toEqual(toAccountStatus(STATUS));
        expect(api.requests.map((request) => request.headers.authorization)).toEqual([`Bearer ${KEY}`]);
    });

    it('raises the proxy’s 401 as Unauthenticated, saying the app’s session ended', async () => {
        const error = await readAccountStatus(throughTheApp()).catch((caught: unknown) => caught);
        expect(error).toBeInstanceOf(Unauthenticated);
        expect((error as Unauthenticated).details.reason).toBe('signed_out');
    });

    it('reads NoClick from server code with the server client, which holds the key', async () => {
        const status = await serverClient(config(), { maxRetries: 0 }).request('GET', '/v1/status');
        expect(status).toEqual(STATUS);
        expect(api.requests[0].headers.authorization).toBe(`Bearer ${KEY}`);
    });
});

it('never puts the key, the password or the session secret in anything it answered or logged', () => {
    expect(transcript.length).toBeGreaterThan(60);
    for (const text of [...transcript, ...consoleOutput]) {
        for (const secret of [KEY, PASSWORD, SECRET, 'nk_test_first', 'nk_test_carriage', 'nk_test_with space']) expect(text.includes(secret)).toBe(false);
    }
});

/** `promise`, or a failure naming what didn't happen after `ms`. */
function within<T>(promise: Promise<T>, ms: number, failure: string): Promise<T> {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const timeout = new Promise<never>((_, reject) => {
        timer = setTimeout(() => reject(new Error(failure)), ms);
    });
    return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
}
