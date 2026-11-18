// What the server tests run against: the app itself, loaded by Vite the way `react-router dev` loads it and answered by
// React Router's own request handler (middleware, the server entry, data requests and resource routes as in
// production), and a fake NoClick API on a local port that records every request it gets. No network, no NoClick
// account. test/served.test.ts runs the built app under its production server instead.
import { createServer as createHttpServer, type IncomingHttpHeaders, type ServerResponse } from 'node:http';
import type { AddressInfo } from 'node:net';
import { resolve } from 'node:path';
import { gzipSync } from 'node:zlib';
import { createRequestHandler, type ServerBuild } from 'react-router';
import { createServer as createViteServer } from 'vite';

const APP = resolve(import.meta.dirname, '..');

export interface App {
    handle: (request: Request) => Promise<Response>;
    close: () => Promise<void>;
}

export async function startApp(): Promise<App> {
    const vite = await createViteServer({
        root: APP,
        configFile: resolve(APP, 'vite.config.ts'),
        appType: 'custom',
        logLevel: 'warn',
        server: { middlewareMode: true, hmr: false, ws: false },
    });
    const build = (await vite.ssrLoadModule('virtual:react-router/server-build')) as ServerBuild;
    const handler = createRequestHandler(build, 'production');
    return { handle: (request) => handler(request), close: () => vite.close() };
}

export interface Recorded {
    method: string;
    url: string;
    headers: IncomingHttpHeaders;
    body: string;
}

/** A promise with its resolve, for a test and the fake API to wait on each other. */
export interface Signal {
    promise: Promise<void>;
    resolve: () => void;
}

export function signal(): Signal {
    let resolve!: () => void;
    const promise = new Promise<void>((done) => (resolve = done));
    return { promise, resolve };
}

export const STATUS = {
    object: 'status',
    account: { id: 'acct_7f3a', name: 'Ana Lima', email: 'ana@example.com', acting_for: null },
    user_id: null,
    plan: { name: 'member', billing: 'at_cost' },
    balance: { remaining_usd: 42.5, included_usd: 10, funds_usd: 32.5, unlimited: false },
    month: { period_start: '2026-11-01T00:00:00+00:00', resets_at: '2026-12-01T00:00:00+00:00', spent_usd: 7.25 },
    caps: [],
};

/** Headers the API may send that act on whichever origin shows them, and the ones the SDK and a download need. */
export const ORIGIN_WIDE_HEADERS = {
    'report-to': '{"group":"g","max_age":604800,"endpoints":[{"url":"https://reports.example/r"}]}',
    nel: '{"report_to":"g","max_age":604800}',
    'reporting-endpoints': 'g="https://reports.example/r"',
    'clear-site-data': '"cookies"',
    refresh: '0; url=https://elsewhere.example/',
    link: '<https://elsewhere.example/style.css>; rel=preload; as=style',
    'permissions-policy': 'camera=*',
    'content-security-policy-report-only': "default-src 'none'; report-uri https://reports.example/r",
    'service-worker-allowed': '/',
    'timing-allow-origin': '*',
    'access-control-allow-origin': '*',
    'strict-transport-security': 'max-age=63072000',
    'x-powered-by': 'something',
};
export const NEEDED_HEADERS = {
    'content-disposition': 'attachment; filename="report.csv"',
    'content-language': 'en',
    'content-range': 'bytes 0-1/2',
    'accept-ranges': 'bytes',
    etag: '"v1"',
    'last-modified': 'Wed, 18 Nov 2026 10:00:00 GMT',
    'retry-after': '3',
    'idempotent-replayed': 'true',
    'x-request-id': 'req_fake_2',
    'cf-ray': 'ray_fake_2',
};

/** One event stream the fake API is sending: it sends its second event when released, and says if it was cut off. */
export interface FakeStream {
    release: () => void;
    /** Resolved if the connection closed before the stream ended (the app's server stopped listening). */
    goneEarly: Promise<void>;
}

export interface FakeApi {
    url: string;
    requests: Recorded[];
    /** Every /v1/stream request, as it arrives. */
    streams: FakeStream[];
    /** Resolved when the next /v1/echo request has received its first chunk of body. */
    firstChunkOfNextEcho: () => Promise<void>;
    close: () => Promise<void>;
}

/** NoClick's API as far as these tests need it. Every request is recorded (`requests`), headers and body. */
export async function startFakeApi(): Promise<FakeApi> {
    const requests: Recorded[] = [];
    const streams: FakeStream[] = [];
    const echoWaiters: Signal[] = [];
    const json = (res: ServerResponse, status: number, body: unknown, headers: Record<string, string | string[]> = {}) => {
        res.writeHead(status, { 'content-type': 'application/json', ...headers });
        res.end(JSON.stringify(body));
    };
    const server = createHttpServer((req, res) => {
        const record: Recorded = { method: req.method ?? '', url: req.url ?? '', headers: req.headers, body: '' };
        requests.push(record);
        const path = (req.url ?? '').split('?')[0];
        if (path === '/v1/stream') {
            const release = signal();
            const goneEarly = signal();
            streams.push({ release: release.resolve, goneEarly: goneEarly.promise });
            res.on('close', () => {
                if (!res.writableEnded) goneEarly.resolve();
            });
            res.writeHead(200, { 'content-type': 'text/event-stream', 'cache-control': 'no-cache' });
            res.write('event: message\ndata: {"n":1}\n\n');
            void release.promise.then(() => res.end('event: message\ndata: {"n":2}\n\n'));
            return;
        }
        const firstChunk = path === '/v1/echo' ? echoWaiters.shift() : undefined;
        req.on('data', (chunk: Buffer) => {
            record.body += chunk.toString();
            firstChunk?.resolve();
        });
        req.on('end', () => {
            if (path === '/v1/status') {
                return json(res, 200, STATUS, {
                    'set-cookie': ['api_session=upstream; Path=/; HttpOnly'],
                    'strict-transport-security': 'max-age=63072000',
                    'access-control-allow-origin': '*',
                    'x-request-id': 'req_fake_1',
                });
            }
            if (path === '/v1/headers') {
                // Echoes the request's Authorization in a header, as a careless or hostile upstream might.
                return json(res, 200, {}, { ...ORIGIN_WIDE_HEADERS, ...NEEDED_HEADERS, 'x-echo-authorization': String(req.headers.authorization) });
            }
            if (path === '/v1/echo') return json(res, 200, { received: record.body });
            if (path === '/v1/gzipped') {
                res.writeHead(200, { 'content-type': 'application/json', 'content-encoding': 'gzip' });
                return res.end(gzipSync(JSON.stringify({ compressed: true })));
            }
            if (path === '/v1/moved') {
                res.writeHead(307, { location: `http://${req.headers.host}/v1/status?from=moved` });
                return res.end();
            }
            if (path === '/v1/nothing') {
                res.writeHead(204);
                return res.end();
            }
            json(res, 404, { error: { type: 'not_found', message: `No route ${path}` } });
        });
    });
    await new Promise<void>((done) => server.listen(0, '127.0.0.1', done));
    const { port } = server.address() as AddressInfo;
    return {
        url: `http://127.0.0.1:${port}`,
        requests,
        streams,
        firstChunkOfNextEcho: () => {
            const waiter = signal();
            echoWaiters.push(waiter);
            return waiter.promise;
        },
        close: () =>
            new Promise<void>((done) => {
                server.closeAllConnections();
                server.close(() => done());
            }),
    };
}

/** The `name=value` a Set-Cookie header sets, for a Cookie header. */
export function cookieOf(response: Response): string {
    const header = response.headers.get('set-cookie');
    if (!header) throw new Error(`no Set-Cookie on a ${response.status}`);
    return header.split(';')[0];
}

/** Everything a response told the browser, headers and body, to search for something that must not be there. */
export async function everything(response: Response): Promise<string> {
    const headers = [...response.headers].map(([name, value]) => `${name}: ${value}`).join('\n');
    return `${response.status}\n${headers}\n\n${await response.text()}`;
}
