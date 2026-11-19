// @vitest-environment happy-dom
// A machine's shell lasts 15 minutes at a time on its socket: asked to renew while it's open, the page's connection
// asks for the machine's shell again and answers with the new token, so the person's bash goes on unbroken.
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { NoClick } from 'noclick';
import { openMachineShell } from './machineApi';

class FakeSocket {
    static last: FakeSocket;
    binaryType = 'blob';
    sent: unknown[] = [];
    onopen: (() => void) | null = null;
    onmessage: ((event: { data: unknown }) => void) | null = null;
    onclose: ((event: { code: number; reason: string }) => void) | null = null;
    constructor(readonly url: string) {
        FakeSocket.last = this;
    }
    send(data: unknown) {
        this.sent.push(data);
    }
    close() {}
}

beforeEach(() => vi.stubGlobal('WebSocket', FakeSocket));
afterEach(() => vi.unstubAllGlobals());

it('an open machine shell renews itself with a new shell token', async () => {
    const tokens = ['tok-1', 'tok-2'];
    const asked: string[] = [];
    const client = new NoClick({
        apiKey: 'sk_test',
        baseUrl: 'https://api.noclick.test',
        maxRetries: 0,
        fetch: (async (input: RequestInfo | URL, init?: RequestInit) => {
            const method = init?.method ?? 'GET';
            asked.push(`${method} ${new URL(String(input)).pathname}`);
            const body =
                method === 'POST'
                    ? {
                          object: 'machine_shell',
                          machine_id: 'm-1',
                          url: 'wss://api.noclick.test/v1/terminals/attach',
                          token: tokens.shift(),
                          token_expires_at: null,
                          idle_limit_s: 900,
                      }
                    : { object: 'machine', id: 'm-1', name: 'support-box', status: 'running' };
            return new Response(JSON.stringify(body), {
                status: 200,
                headers: { 'content-type': 'application/json' },
            });
        }) as typeof fetch,
    });
    const shell = await openMachineShell(client, 'm-1', null);
    shell.connect();
    const socket = FakeSocket.last;
    socket.onopen?.();
    expect(JSON.parse(socket.sent[0] as string).renew).toBe(true); // it renews, and says so
    socket.onmessage?.({ data: JSON.stringify({ type: 'ready', state: 'open' }) });
    socket.onmessage?.({ data: JSON.stringify({ type: 'renew' }) });
    await vi.waitFor(() => expect(socket.sent).toHaveLength(2));
    expect(asked.filter((call) => call.startsWith('POST'))).toEqual([
        'POST /v1/machines/m-1/shell',
        'POST /v1/machines/m-1/shell',
    ]);
    expect(JSON.parse(socket.sent[1] as string)).toEqual({
        type: 'renew',
        token: 'tok-2',
    });
});
