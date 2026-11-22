// The app as `npm start` serves it: built, then run by react-router-serve on a local port, against a fake NoClick
// API. Pins that the gate sees every request React Router answers (the ones it answers without middleware too), what
// the server answers without the gate (static files, React Router's manifest, and the few requests the HTTP server
// refuses before React Router), that none of those answers carries anything of the app's, that events stream, and
// that the built app serves the developer console and nothing of its labs.
import { spawn, spawnSync, type ChildProcess } from 'node:child_process';
import { readdirSync, readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { connect, createServer, type AddressInfo } from 'node:net';
import { dirname, join, resolve } from 'node:path';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { BROWSER_BEARER } from '@/sdk/proxied';
import { startFakeApi, type FakeApi } from './harness';

const APP = resolve(import.meta.dirname, '..');
const KEY = 'nk_test_served';
const PASSWORD = 'amber valley compass 17';
const SECRET = 'a session secret only the served tests use';
const BEARER = { authorization: `Bearer ${BROWSER_BEARER}` };

const require = createRequire(import.meta.url);
const cli = (pkg: string) => join(dirname(require.resolve(`${pkg}/package.json`)), 'bin.js');

interface Served {
    url: string;
    port: number;
    output: string[];
    process: ChildProcess;
}

let api: FakeApi;
let configured: Served;
let unset: Served;
/** Everything the servers answered or printed, to search for secrets at the end. */
const transcript: string[] = [];

async function freePort(): Promise<number> {
    const server = createServer();
    await new Promise<void>((done) => server.listen(0, '127.0.0.1', done));
    const { port } = server.address() as AddressInfo;
    await new Promise<void>((done) => server.close(() => done()));
    return port;
}

/** The shell's environment without the app's settings and without NODE_ENV, which the test runner sets to `test`: the
 *  build and the server then run as `pnpm build` and `pnpm start` run them. */
function shellEnv(): Record<string, string | undefined> {
    return Object.fromEntries(Object.entries(process.env).filter(([name]) => !['NOCLICK_API_KEY', 'NOCLICK_API_URL', 'APP_PASSWORD', 'SESSION_SECRET', 'NODE_ENV'].includes(name)));
}

/** Runs the built app on a port of its own with `env` as its settings, and waits until it answers. */
async function serve(env: Record<string, string>): Promise<Served> {
    const port = await freePort();
    // Only the settings given: none from the shell running the tests.
    const inherited = shellEnv();
    const child = spawn(process.execPath, [cli('@react-router/serve'), 'build/server/index.js'], {
        cwd: APP,
        env: { ...inherited, ...env, PORT: String(port), HOST: '127.0.0.1' },
        stdio: ['ignore', 'pipe', 'pipe'],
    });
    const output: string[] = [];
    child.stdout.on('data', (chunk) => output.push(String(chunk)));
    child.stderr.on('data', (chunk) => output.push(String(chunk)));
    const url = `http://127.0.0.1:${port}`;
    for (let tries = 0; ; tries++) {
        try {
            await fetch(`${url}/login`);
            return { url, port, output, process: child };
        } catch {
            if (tries > 100 || child.exitCode !== null) throw new Error(`the server didn't start:\n${output.join('')}`);
            await new Promise((resolve) => setTimeout(resolve, 100));
        }
    }
}

/** One request written as raw HTTP, for the ones fetch won't send; the whole answer as text. */
function raw(served: Served, request: string): Promise<string> {
    return new Promise((resolve) => {
        const socket = connect(served.port, '127.0.0.1');
        let answer = '';
        socket.on('data', (chunk) => (answer += chunk.toString('latin1')));
        socket.on('close', () => resolve(answer));
        socket.on('error', (error) => resolve(`socket error ${(error as NodeJS.ErrnoException).code}`));
        socket.setTimeout(5_000, () => socket.destroy());
        socket.write(request.replace(/\n/g, '\r\n'));
    });
}

async function get(served: Served, path: string, init: RequestInit = {}) {
    const response = await fetch(served.url + path, { redirect: 'manual', ...init });
    const body = await response.text();
    transcript.push(`${response.status}\n${[...response.headers].map(([n, v]) => `${n}: ${v}`).join('\n')}\n\n${body}`);
    return { status: response.status, headers: response.headers, body };
}

beforeAll(async () => {
    const built = spawnSync(process.execPath, [cli('@react-router/dev'), 'build'], { cwd: APP, encoding: 'utf8', env: shellEnv() });
    if (built.status !== 0) throw new Error(`the build failed:\n${built.stdout}\n${built.stderr}`);
    api = await startFakeApi();
    const settings = { NOCLICK_API_KEY: KEY, APP_PASSWORD: PASSWORD, SESSION_SECRET: SECRET, NOCLICK_API_URL: api.url };
    [configured, unset] = await Promise.all([serve(settings), serve({ ...settings, SESSION_SECRET: '' })]);
}, 180_000);

afterAll(async () => {
    for (const served of [configured, unset]) served?.process.kill();
    await api?.close();
});

describe('the gate, under the production server', () => {
    it('sees every request React Router answers, the ones it answers without middleware included', async () => {
        for (const [method, path, status, location] of [
            ['GET', '/', 302, '/login'],
            ['OPTIONS', '/', 302, '/login'],
            ['PROPFIND', '/', 302, '/login'],
            ['GET', '/x%0a', 302, '/login?next=%2Fx%250a'],
            ['GET', '//evil.example/x', 302, '/login?next=%2F%2Fevil.example%2Fx'],
        ] as const) {
            const answer = await get(configured, path, { method });
            expect(answer.status, `${method} ${path}`).toBe(status);
            expect(answer.headers.get('location'), `${method} ${path}`).toBe(location);
            expect(answer.headers.get('x-frame-options'), `${method} ${path}`).toBe('DENY');
        }
        expect((await get(configured, '/api/v1/status', { headers: BEARER })).status).toBe(401);
        expect((await get(configured, '/_root.data')).body).toContain('"/login"');
        expect(api.requests).toEqual([]);
    });

    it('serves the static files to anyone, and React Router’s own manifest', async () => {
        const css = readdirSync(join(APP, 'build/client/assets')).find((name) => name.endsWith('.css'))!;
        const style = await get(configured, `/assets/${css}`);
        expect(style.status).toBe(200);
        expect(style.headers.get('cache-control')).toContain('immutable');
        const manifest = await get(configured, '/__manifest?paths=%2F&version=another');
        expect(manifest.status).toBe(204);
        expect(manifest.body).toBe('');
    });

    it('answers a few requests before React Router, with a bare error page, and keeps serving', async () => {
        const host = `Host: 127.0.0.1:${configured.port}`;
        for (const [request, status] of [
            [`GET /%zz HTTP/1.1\n${host}\nConnection: close\n\n`, 400],
            [`GET /api/v1/%zz HTTP/1.1\n${host}\nConnection: close\n\n`, 400],
            [`TRACE / HTTP/1.1\n${host}\nConnection: close\n\n`, 500],
            [`OPTIONS * HTTP/1.1\n${host}\nConnection: close\n\n`, 500],
            [`GET / HTTP/1.1\nHost: [\nConnection: close\n\n`, 500],
            [`GET / HTTP/1.0\n\n`, 500],
        ] as const) {
            const answer = await raw(configured, request);
            transcript.push(answer);
            const what = request.split('\n')[0];
            expect(answer, what).toMatch(new RegExp(`^HTTP/1\\.1 ${status} `));
            const body = answer.slice(answer.indexOf('\r\n\r\n') + 4);
            expect(body, what).toMatch(/<pre>(Bad Request|Internal Server Error)<\/pre>/);
            expect(body, what).not.toMatch(/NoClick|<script|at \w/);
        }
        expect((await get(configured, '/login')).status).toBe(200);
    });

    it('streams events to a signed-in owner as they come, compression asked for or not', async () => {
        const signedIn = await get(configured, '/login', {
            method: 'POST',
            body: new URLSearchParams({ password: PASSWORD }),
            headers: { origin: configured.url },
        });
        expect(signedIn.status).toBe(302);
        const cookie = signedIn.headers.get('set-cookie')!.split(';')[0];
        const response = await fetch(`${configured.url}/api/v1/stream`, {
            headers: { ...BEARER, cookie, accept: 'text/event-stream', 'accept-encoding': 'gzip' },
        });
        expect(response.status).toBe(200);
        expect(response.headers.get('content-encoding')).toBeNull();
        const reader = response.body!.getReader();
        const first = await Promise.race([reader.read(), new Promise<never>((_, reject) => setTimeout(() => reject(new Error('the first event waited for the stream to end')), 5_000))]);
        expect(new TextDecoder().decode(first.value)).toContain('{"n":1}');
        api.streams.at(-1)!.release();
        await reader.cancel();
        expect(api.requests.at(-1)!.headers.authorization).toBe(`Bearer ${KEY}`);
    });
});

describe('the developer console, under the production server', () => {
    /** Every file the build made, by its path under build/. */
    function builtFiles(dir = join(APP, 'build')): string[] {
        return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => (entry.isDirectory() ? builtFiles(join(dir, entry.name)) : [join(dir, entry.name)]));
    }

    async function signedInCookie(): Promise<string> {
        const signedIn = await get(configured, '/login', { method: 'POST', body: new URLSearchParams({ password: PASSWORD }), headers: { origin: configured.url } });
        return signedIn.headers.get('set-cookie')!.split(';')[0];
    }

    it('is behind the sign-in, and served to the owner at /developers and every page under it', async () => {
        expect((await get(configured, '/developers')).headers.get('location')).toBe('/login?next=%2Fdevelopers');
        const cookie = await signedInCookie();
        for (const path of ['/developers', '/developers/usage', '/developers/resources/apps']) {
            const page = await get(configured, path, { headers: { cookie } });
            expect(page.status, path).toBe(200);
            expect(page.body, path).toContain('<title>Developers · NoClick</title>');
            expect(page.headers.get('x-frame-options'), path).toBe('DENY');
        }
    });

    it('serves Work to the owner at /work, behind the sign-in', async () => {
        expect((await get(configured, '/work')).headers.get('location')).toBe('/login?next=%2Fwork');
        const cookie = await signedInCookie();
        for (const path of ['/work', '/work?space=home&show=agents']) {
            const page = await get(configured, path, { headers: { cookie } });
            expect(page.status, path).toBe(200);
            expect(page.body, path).toContain('<title>Work · NoClick</title>');
            expect(page.headers.get('x-frame-options'), path).toBe('DENY');
        }
    });

    it('serves the chat to the owner at /chat, behind the sign-in', async () => {
        expect((await get(configured, '/chat')).headers.get('location')).toBe('/login?next=%2Fchat');
        const cookie = await signedInCookie();
        const page = await get(configured, '/chat', { headers: { cookie } });
        expect(page.status).toBe(200);
        expect(page.body).toContain('<title>Chat · NoClick</title>');
        expect(page.headers.get('x-frame-options')).toBe('DENY');
    });

    it('serves Connections to the owner at /connections, behind the sign-in', async () => {
        expect((await get(configured, '/connections')).headers.get('location')).toBe('/login?next=%2Fconnections');
        const cookie = await signedInCookie();
        for (const path of ['/connections', '/connections?view=connected&account=credential%3Ac_1']) {
            const page = await get(configured, path, { headers: { cookie } });
            expect(page.status, path).toBe(200);
            expect(page.body, path).toContain('<title>Connections · NoClick</title>');
            expect(page.headers.get('x-frame-options'), path).toBe('DENY');
        }
    });

    it('serves Settings to the owner at /settings, behind the sign-in', async () => {
        expect((await get(configured, '/settings')).headers.get('location')).toBe('/login?next=%2Fsettings');
        const cookie = await signedInCookie();
        for (const path of ['/settings', '/settings?section=billing']) {
            const page = await get(configured, path, { headers: { cookie } });
            expect(page.status, path).toBe(200);
            expect(page.body, path).toContain('<title>Settings · NoClick</title>');
            expect(page.headers.get('x-frame-options'), path).toBe('DENY');
        }
    });

    it('serves the workflows and one workflow’s page to the owner, behind the sign-in', async () => {
        expect((await get(configured, '/workflows')).headers.get('location')).toBe('/login?next=%2Fworkflows');
        expect((await get(configured, '/workflows/wf_1?tab=setup')).headers.get('location')).toBe('/login?next=%2Fworkflows%2Fwf_1%3Ftab%3Dsetup');
        const cookie = await signedInCookie();
        for (const [path, title] of [['/workflows', 'Automations'], ['/workflows/wf_1', 'Workflow'], ['/workflows/wf_1?tab=test', 'Workflow']] as const) {
            const page = await get(configured, path, { headers: { cookie } });
            expect(page.status, path).toBe(200);
            expect(page.body, path).toContain(`<title>${title} · NoClick</title>`);
            expect(page.headers.get('x-frame-options'), path).toBe('DENY');
        }
    });

    it('draws the home, the chat, Work, Automations, Connections, Resources and Settings in the app’s frame, and the console in it with its own sidebar', async () => {
        const cookie = await signedInCookie();
        for (const path of ['/', '/chat', '/work', '/workflows', '/workflows/wf_1', '/connections', '/resources?kind=domains', '/settings']) {
            const page = await get(configured, path, { headers: { cookie } });
            expect(page.status, path).toBe(200);
            expect(page.body, path).toContain('data-testid="app-sidebar"');
            expect(page.body, path).toContain('aria-label="Main"');
        }
        const developers = await get(configured, '/developers', { headers: { cookie } });
        expect(developers.status).toBe(200);
        expect(developers.body).toContain('data-testid="app-sidebar"');
        expect(developers.body).toContain('aria-label="Developer console"');
        expect(developers.body).not.toContain('aria-label="Main"');
    });

    it('has no lab: its address answers 404, and the build carries none of its made-up data', async () => {
        const cookie = await signedInCookie();
        for (const path of ['/developers-lab', '/developers-lab/usage?fixture=populated', '/resources-lab', '/work-lab', '/work-lab?scene=home&as=key', '/chat-lab', '/chat-lab?scene=start&as=key', '/connections-lab', '/connections-lab?scene=account&as=key', '/settings-lab', '/settings-lab?scene=billing&as=key', '/workflows-lab', '/workflows-lab?scene=canvas&as=key', '/step-form-lab', '/step-form-lab?scene=mail-send&as=key']) {
            expect((await get(configured, path, { headers: { cookie } })).status, path).toBe(404);
        }
        const files = builtFiles();
        expect(files.length).toBeGreaterThan(20);
        // The console lab's own note, a value only its fixtures hold (the moment they are set at), a made-up agent of
        // Work's fixtures, the chat's fixtures' NoClick, a made-up bot of Connections' fixtures, and a made-up folder
        // of the workflows' fixtures.
        const carrying = files.filter((file) => /\.(?:js|mjs|css|html|json)$/.test(file)).filter((file) => /Lab: made-up data|2026-09-26T16:20:05|agt_wirefern|8d6f1d3a-0c4e-4d55-9a5b-1f6f2c7b9e01|northwind-release-bot|fld_reports/.test(readFileSync(file, 'utf8')));
        expect(carrying.map((file) => file.slice(APP.length + 1))).toEqual([]);
    });
});

describe('the production server with a setting missing', () => {
    it('answers the setup page on every request React Router answers, naming the setting and no value', async () => {
        const page = await get(unset, '/');
        expect(page.status).toBe(503);
        expect(page.body).toContain('Finish setting up this app');
        expect(page.body).toContain('SESSION_SECRET');
        // Drawn with the app's own stylesheet.
        expect(page.body).toMatch(/<link rel="stylesheet" href="\/assets\/[^"]+\.css"/);
        for (const [method, path] of [['OPTIONS', '/'], ['GET', '/x%0a'], ['POST', '/login']] as const) {
            const answer = await get(unset, path, { method, headers: { origin: unset.url } });
            expect(answer.status, `${method} ${path}`).toBe(503);
            expect(answer.body, `${method} ${path}`).toContain('SESSION_SECRET');
        }
        const proxied = await get(unset, '/api/v1/status', { headers: BEARER });
        expect(proxied.status).toBe(503);
        expect(JSON.parse(proxied.body).error.missing).toEqual(['SESSION_SECRET']);
        expect(api.requests.filter((request) => request.url === '/v1/status')).toEqual([]);
    });
});

it('never puts the key, the password or the session secret in anything the servers answered or printed', () => {
    expect(transcript.length).toBeGreaterThan(15);
    for (const text of [...transcript, ...configured.output, ...unset.output]) {
        for (const secret of [KEY, PASSWORD, SECRET]) expect(text.includes(secret)).toBe(false);
    }
});
