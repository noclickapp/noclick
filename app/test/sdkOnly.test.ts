// The app's screens reach NoClick through the SDK and nothing else: no socket library, no untyped `client.request('POST', …)`,
// no raw `fetch`, and no server code reading data itself. What still does is listed in sdkOnly.allow.ts with why, and
// the list only shrinks: a file's count may not go up, and one that goes down takes the list down with it.
import { join, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { SCAN_S } from './limits';
import { ALLOW } from './sdkOnly.allow';
import { hitsIn, judge, modulesUnder, scan } from './sdkOnlyScan';

const APP = resolve(import.meta.dirname, '..');

describe('the scanner', () => {
    it('counts a socket library, an untyped call, a raw network call and server code reading data itself', () => {
        expect(
            hitsIn(
                'src/screens/page.tsx',
                [
                    "import { sendEventAsync } from '~/lib/socket-sender';",
                    "import type { Socket } from 'socket.io-client';",
                    "sendEventAsync({ event_name: 'workflow:get' });",
                    "await client.request('POST', '/v1/things', { json: {} });",
                    "await client.request(method, path);",
                    "await fetch('/payment/portal');",
                    "await thing.fetch();",
                    "navigator.sendBeacon('/t', body);",
                    "new WebSocket('wss://x');",
                ].join('\n'),
            ),
        ).toEqual([
            'socket: imports ~/lib/socket-sender',
            'socket: calls sendEventAsync',
            "untyped: request('POST', ...)",
            'network: fetch',
            'network: sendBeacon',
            'network: new WebSocket',
        ]);
        expect(hitsIn('src/routes/page.server.ts', "import { Pool } from 'pg';\nconst url = '/v1/account';")).toEqual([
            'server data: imports pg',
            "server data: '/v1/account'",
        ]);
        // Outside server code a path is only a string.
        expect(hitsIn('src/screens/page.tsx', "const url = '/v1/account';")).toEqual([]);
    });

    it('fails a new file, a count that moved either way, a stale entry and a pending naming no change', () => {
        expect(
            judge(
                { 'a.ts': ['network: fetch'], 'b.ts': ['network: fetch', 'network: fetch'], 'c.ts': ['network: fetch'] },
                {
                    'b.ts': { count: 1, why: 'third-party' },
                    'c.ts': { count: 2, why: 'pending', chunk: 3 },
                    'd.ts': { count: 1, why: 'pending' },
                },
            ),
        ).toEqual([
            'a.ts: 1 new (network: fetch): go through the SDK, or list it with why',
            'b.ts: 2 where 1 are allowed (network: fetch)',
            'c.ts: down to 1 from 2: lower its count in the allowlist',
            'd.ts: nothing left to allow: take it out of the allowlist',
            'd.ts: pending names no change (2 to 4)',
        ]);
    });
});

describe('the app', () => {
    it('reaches NoClick around the SDK only where the allowlist says why', () => {
        expect(judge(scan(modulesUnder(join(APP, 'src'), APP)), ALLOW).join('\n')).toBe('');
    }, SCAN_S);
});
