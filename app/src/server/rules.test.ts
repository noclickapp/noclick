// The server's rules on their own: what counts as usable settings, what the proxy forwards and answers, a request
// from another site, a request served on this machine, and where to go after signing in. test/server.test.ts runs
// them in the app, behind the gate (which sets some of the same headers again).
import { DEFAULT_BASE_URL } from 'noclick';
import { describe, expect, it } from 'vitest';
import { BROWSER_BEARER } from '@/sdk/proxied';
import { checkConfig, noclickApiKey } from './config.server';
import { crossSite, isLoopbackHost, servedLocally } from './origin.server';
import { apiPathOf, forward } from './proxy.server';
import { checkPassword, safeNext } from './signIn.server';

const USABLE = {
    NOCLICK_API_KEY: 'nk_test_rules',
    APP_PASSWORD: 'quiet-meadow-paper-91',
    SESSION_SECRET: 'a session secret only the rule tests use',
};

describe('settings', () => {
    it('takes usable settings, NoClick’s API by default, and never puts the key in the config', () => {
        const check = checkConfig(USABLE);
        expect(check).toEqual({ ok: true, config: { password: USABLE.APP_PASSWORD, sessionSecret: USABLE.SESSION_SECRET, apiUrl: DEFAULT_BASE_URL, keyGiven: false } });
        expect(JSON.stringify(check)).not.toContain(USABLE.NOCLICK_API_KEY);
        expect(noclickApiKey(USABLE)).toBe(USABLE.NOCLICK_API_KEY);
        expect(() => noclickApiKey({})).toThrow('NOCLICK_API_KEY is not set, or not one line of printable characters.');
    });

    it('knows a key NoClick gave it from one somebody set, and says so where NoClick’s hosting gave it none', () => {
        // The bearer NoClick's app hosting hands a production release of an app whose repository asks for a key.
        expect(checkConfig({ ...USABLE, NOCLICK_API_KEY: 'nk_app_given.by.noclick' })).toMatchObject({ ok: true, config: { keyGiven: true } });
        const HOSTED = { NOCLICK_PROJECT_ID: 'prj_1', NOCLICK_DEPLOYMENT_TOKEN: 'nk_dep_release' };
        const preview = checkConfig({ ...USABLE, ...HOSTED, NOCLICK_API_KEY: '' });
        expect(preview.ok).toBe(false);
        if (preview.ok) return;
        expect(preview.problems).toEqual([expect.objectContaining({ name: 'NOCLICK_API_KEY', given: true, problem: 'is given to this app by NoClick, and this release has none.' })]);
        expect(preview.problems[0].fix).toContain('once the account’s owner approves');
        expect(preview.problems[0].fix).not.toContain('developer console');
        // Anywhere else a missing key is the deployer's to create and set.
        const elsewhere = checkConfig({ ...USABLE, NOCLICK_API_KEY: '' });
        expect(elsewhere.ok ? [] : elsewhere.problems).toEqual([expect.objectContaining({ name: 'NOCLICK_API_KEY', problem: 'is not set.' })]);
        expect(elsewhere.ok ? null : elsewhere.problems[0].given).toBeUndefined();
    });

    it.each([
        ['a line break', 'nk_test_first\nnk_test_second'],
        ['a Windows line ending', 'nk_test_rules\r'],
        ['a space around it', ' nk_test_rules'],
        ['a space inside', 'nk_test rules'],
        ['a tab', 'nk_test\trules'],
        ['a character outside ASCII', 'nk_test_rülés'],
    ])('refuses a key with %s, naming it and never its value', (_, key) => {
        const check = checkConfig({ ...USABLE, NOCLICK_API_KEY: key });
        expect(check.ok).toBe(false);
        if (check.ok) return;
        expect(check.problems).toEqual([expect.objectContaining({ name: 'NOCLICK_API_KEY', problem: 'has a space, a line break or another character a key never has.' })]);
        expect(JSON.stringify(check)).not.toContain('rules');
        expect(() => noclickApiKey({ NOCLICK_API_KEY: key })).toThrow(/^NOCLICK_API_KEY is not set, or not one line of printable characters\.$/);
    });

    it.each([
        ['https://api.example.com/', 'https://api.example.com'],
        ['https://api.example.com/noclick/', 'https://api.example.com/noclick'],
        ['http://localhost:8000', 'http://localhost:8000'],
        ['http://127.0.0.1:8000/', 'http://127.0.0.1:8000'],
        ['http://[::1]:8000', 'http://[::1]:8000'],
    ])('takes NOCLICK_API_URL %j as %j', (value, apiUrl) => {
        expect(checkConfig({ ...USABLE, NOCLICK_API_URL: value })).toMatchObject({ ok: true, config: { apiUrl } });
    });

    it.each([
        ['http://api.example.com', 'must use https'],
        ['https://user:pass@api.example.com', 'no sign-in details'],
        ['https://api.example.com/?region=eu', 'no sign-in details, query or fragment'],
        ['ftp://api.example.com', 'must use https'],
        ['api.example.com', 'is not a URL'],
    ])('refuses NOCLICK_API_URL %j', (value, problem) => {
        const check = checkConfig({ ...USABLE, NOCLICK_API_URL: value });
        expect(check.ok).toBe(false);
        if (check.ok) return;
        expect(check.problems).toHaveLength(1);
        expect(check.problems[0].name).toBe('NOCLICK_API_URL');
        expect(check.problems[0].problem).toContain(problem);
        expect(JSON.stringify(check)).not.toContain('api.example.com');
    });

    it('counts a password’s characters, not its bytes, and names each problem once without its value', () => {
        expect(checkConfig({ ...USABLE, APP_PASSWORD: 'ñandú-ñandú' }).ok).toBe(false);
        expect(checkConfig({ ...USABLE, APP_PASSWORD: 'ñandú-ñandú!' }).ok).toBe(true);
        const check = checkConfig({ NOCLICK_API_KEY: '  ', APP_PASSWORD: 'short-pw', SESSION_SECRET: 'not-long-enough' });
        expect(check.ok).toBe(false);
        if (check.ok) return;
        expect(check.problems.map((p) => [p.name, p.problem])).toEqual([
            ['NOCLICK_API_KEY', 'is not set.'],
            ['APP_PASSWORD', 'is shorter than 12 characters.'],
            ['SESSION_SECRET', 'is shorter than 32 characters.'],
        ]);
        expect(JSON.stringify(check)).not.toMatch(/short-pw|not-long-enough/);
    });
});

describe('the password check', () => {
    it('compares digests of the text as typed in any Unicode form, not the strings themselves', async () => {
        // "é" as one character (as the setting holds it) and as e plus a combining accent (as some keyboards type it).
        expect(await checkPassword('café lantern 42', 'café lantern 42')).toBe('right');
        expect(await checkPassword('café lantern 42', 'café lantern 42')).toBe('right');
    });
});

describe('the key proxy on its own', () => {
    const UPSTREAM = { apiUrl: 'https://api.example', key: 'nk_test_unit' };

    it('calls with the key and answers with its own headers and the few it passes back, nothing else', async () => {
        const calls: Array<[string, Headers]> = [];
        const response = await forward(new Request('http://app.test/api/v1/status', { headers: { authorization: `Bearer ${BROWSER_BEARER}` } }), UPSTREAM, async (input, init) => {
            calls.push([String(input), new Headers(init?.headers)]);
            return new Response('{}', {
                headers: { 'content-type': 'application/json', 'x-request-id': 'req_1', 'set-cookie': 'a=b', 'report-to': '{}', nel: '{}', 'x-content-type-options': 'off' },
            });
        });
        expect(calls.map(([url, headers]) => [url, headers.get('authorization')])).toEqual([['https://api.example/v1/status', 'Bearer nk_test_unit']]);
        expect(Object.fromEntries(response.headers)).toEqual({
            'content-type': 'application/json',
            'x-request-id': 'req_1',
            'cache-control': 'no-store, no-transform',
            'content-security-policy': "default-src 'none'; frame-ancestors 'none'; sandbox",
            'x-content-type-options': 'nosniff',
            'cross-origin-resource-policy': 'same-origin',
        });
    });

    it('refuses a call without the browser client’s bearer before calling anything', async () => {
        let called = false;
        const response = await forward(new Request('http://app.test/api/v1/status'), UPSTREAM, async () => {
            called = true;
            return new Response('{}');
        });
        expect(response.status).toBe(403);
        expect(called).toBe(false);
    });
});

describe('paths the proxy forwards', () => {
    const forwarded = (path: string) => apiPathOf(new URL(`http://app.test${path}`));

    it('passes an API path on as written, query and encoding included', () => {
        expect(forwarded('/api/v1/agents?limit=5')).toBe('/v1/agents?limit=5');
        expect(forwarded('/api/v1/dicts/settings/items/team%2Fa%20b')).toBe('/v1/dicts/settings/items/team%2Fa%20b');
        expect(forwarded('/api/v1/repos/r_1/files/')).toBe('/v1/repos/r_1/files/');
    });

    it.each([
        '/api/v1',
        '/api/v1/',
        '/api/v2/agents',
        '/apiv1/agents',
        '/api/v1//agents',
        '/api/v1/a//b',
        '/api/v1/a/..%2Fb',
        '/api/v1/%2E',
        '/api/v1/a%2F.%2Fb',
        '/api/v1/a%5Cb',
        '/api/v1/a%0Ab',
        '/api/v1/a%7Fb',
        '/api/v1/a%E0%A4%A',
    ])('refuses %j', (path) => {
        expect(forwarded(path)).toBeNull();
    });
});

describe('requests from other sites', () => {
    const request = (headers: Record<string, string>, url = 'https://app.example/login') => new Request(url, { method: 'POST', headers });

    it('trusts the browser’s Sec-Fetch-Site first, then Origin, and passes a request with neither', () => {
        expect(crossSite(request({ 'sec-fetch-site': 'same-origin' }))).toBe(false);
        expect(crossSite(request({ 'sec-fetch-site': 'none' }))).toBe(false);
        expect(crossSite(request({ 'sec-fetch-site': 'same-site' }))).toBe(true);
        expect(crossSite(request({ 'sec-fetch-site': 'cross-site', origin: 'https://app.example' }))).toBe(true);
        expect(crossSite(request({ origin: 'https://app.example' }))).toBe(false);
        expect(crossSite(request({ origin: 'https://app.example.evil.example' }))).toBe(true);
        expect(crossSite(request({ origin: 'https://app.example:8443' }))).toBe(true);
        expect(crossSite(request({ origin: 'null' }))).toBe(true);
        expect(crossSite(request({}))).toBe(false);
    });

    it('compares the whole origin: the app’s host over another scheme is another site', () => {
        expect(crossSite(request({ origin: 'http://app.example' }))).toBe(true);
        expect(crossSite(request({ origin: 'https://app.example:443' }))).toBe(false);
        // Behind a proxy that took the request over https and passed it on over http.
        const behindTls = 'http://app.example/login';
        expect(crossSite(request({ origin: 'https://app.example', 'x-forwarded-proto': 'https' }, behindTls))).toBe(false);
        expect(crossSite(request({ origin: 'http://app.example', 'x-forwarded-proto': 'https' }, behindTls))).toBe(true);
        expect(crossSite(request({ origin: 'https://app.example' }, behindTls))).toBe(true);
    });
});

describe('served on this machine', () => {
    it.each([
        ['localhost', true],
        ['app.localhost', true],
        ['127.0.0.1', true],
        ['127.4.5.6', true],
        ['[::1]', true],
        ['localhost.example.com', false],
        ['128.0.0.1', false],
        ['example.com', false],
    ])('%s is this machine: %s', (host, loopback) => {
        expect(isLoopbackHost(host)).toBe(loopback);
    });

    it('is not, behind a proxy that forwards to this machine', () => {
        expect(servedLocally(new Request('http://localhost:3000/'))).toBe(true);
        for (const header of ['forwarded', 'x-forwarded-for', 'x-forwarded-host', 'x-forwarded-proto', 'x-real-ip']) {
            expect(servedLocally(new Request('http://localhost:3000/', { headers: { [header]: 'x' } }))).toBe(false);
        }
        expect(servedLocally(new Request('https://app.example/'))).toBe(false);
    });
});

describe('where to go after signing in', () => {
    it.each([
        ['/account?x=1', '/account?x=1'],
        ['/a/./b/../c', '/a/c'],
        ['/%2F%2Fevil.example', '/%2F%2Fevil.example'],
        ['https://evil.example', '/'],
        ['//evil.example', '/'],
        ['/\\evil.example', '/'],
        ['/\t/evil.example', '/'],
        ['/\n/evil.example', '/'],
        ['javascript:alert(1)', '/'],
        // Dot segments that resolve to a path starting `//`, which a browser reads as another site.
        ['/.//evil.example/phish', '/'],
        ['/..//evil.example', '/'],
        ['/a/..//evil.example', '/'],
        ['/%2e//evil.example', '/'],
        ['/%2E%2E//evil.example', '/'],
        ['/login/..//evil.example', '/'],
        ['/.//user:pw@evil.example', '/'],
        ['/./a/../b', '/b'],
        ['/login?next=%2Faccount', '/'],
        [null, '/'],
        [undefined, '/'],
    ])('%j goes to %j', (next, expected) => {
        expect(safeNext(next)).toBe(expected);
    });
});
