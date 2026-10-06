import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

const fixture = vi.hoisted(() => {
    const handlers = new Map<string, (...args: unknown[]) => void>();
    const allHandlers = new Map<string, Array<(...args: unknown[]) => void>>();
    const manager = new Map<string, (...args: unknown[]) => void>();
    return { handlers, allHandlers, manager, getSession: vi.fn(), socket: {
        connected: true, active: false, emit: vi.fn(), connect: vi.fn(),
        on: vi.fn((name: string, callback: (...args: unknown[]) => void) => {
            handlers.set(name, callback);
            allHandlers.set(name, [...(allHandlers.get(name) ?? []), callback]);
        }),
        io: { on: vi.fn((name: string, callback: (...args: unknown[]) => void) => manager.set(name, callback)) },
    } };
});
vi.mock('socket.io-client', () => ({ io: () => fixture.socket }));
vi.mock('~/lib/socket/config', () => ({
    DEFAULT_EVENT_BUFFER_TTL_MS: 1000, SOCKET_CHUNK_SIZE: 1024 * 1024, EventRouting: {},
    createSocketConfig: () => ({ API: { url: 'https://fixture.invalid', events: ['response', 'error', 'workflow:node:output'], options: { autoConnect: false } } }),
}));
vi.mock('~/lib/supabase-client', () => ({ getExistingBrowserClient: () => ({ auth: { getSession: fixture.getSession } }) }));
vi.mock('~/lib/telemetry-socket', () => ({ trackSendDropped: vi.fn() }));

import { profilingStore } from './profiling-store';
import { registerRequestCallback, socketReceiver } from './socket-receiver';
import { sendEvent, sendEventAsync } from './socket-sender';
import { REDACTED_SOCKET_DATA } from './socket-diagnostics';

const SECRET = 'synthetic-socket-secret';
let logs: ReturnType<typeof vi.spyOn>[] = [];
const logged = () => JSON.stringify(logs.flatMap(log => log.mock.calls));

beforeAll(() => {
    vi.stubGlobal('window', { location: { pathname: '/dashboard' } });
    socketReceiver.connect();
    vi.unstubAllGlobals();
});
beforeEach(() => {
    logs = ['log', 'warn', 'error', 'debug'].map(method => vi.spyOn(console, method as 'log').mockImplementation(() => undefined));
    vi.stubGlobal('fetch', vi.fn(() => { throw new Error('Forbidden synthetic fetch'); }));
    vi.stubGlobal('WebSocket', vi.fn(() => { throw new Error('Forbidden synthetic WebSocket'); }));
    vi.stubGlobal('crypto', { randomUUID: () => '00000000-0000-4000-8000-000000000001' });
    vi.stubEnv('NODE_ENV', 'development');
    fixture.socket.connected = true;
    fixture.socket.active = false;
    fixture.socket.emit.mockReset();
    fixture.getSession.mockResolvedValue({ data: { session: { access_token: SECRET } } });
    profilingStore.setEnabled(true);
    profilingStore.clear();
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.unstubAllEnvs(); });
afterAll(() => profilingStore.clear());

describe('actual sender/receiver/profiler diagnostics boundary', () => {
    it.each(['drip:oauth:exchange', 'credential:get', 'credential:create', 'credential:update', 'workflow:collab_token', 'instance_keys:set'])('preserves %s wire and callback content but omits diagnostic data', async eventName => {
        const request = { event_name: eventName, code: SECRET, tag: SECRET,
            credential_data: { client_secret: SECRET, unfamiliar: [SECRET] } };
        const original = JSON.stringify(request);
        const promise = sendEventAsync(request as never, undefined, 1000, 'fixture-sensitive');
        const payload = fixture.socket.emit.mock.calls[0][1];
        expect(payload.code).toBe(SECRET);
        expect(payload.credential_data).toBe(request.credential_data);
        expect(JSON.stringify(request)).toBe(original);
        const response = { credential_data: { access_token: SECRET }, opaque: SECRET };
        socketReceiver.injectWireEvent('response', { request_id: 'fixture-sensitive', error: null, data: response });
        expect(await promise).toBe(response);
        const [entry] = profilingStore.getEntries();
        expect(entry.eventName).toBe(eventName);
        expect(entry.requestData).toBe(REDACTED_SOCKET_DATA);
        expect(entry.responseData).toBe(REDACTED_SOCKET_DATA);
        expect(entry.tag).toBe(REDACTED_SOCKET_DATA);
        expect(entry.duration).toEqual(expect.any(Number));
        expect(entry.success).toBe(true);
        expect(logged()).not.toContain(SECRET);
    });

    it('omits sensitive errors but delivers the original callback error', async () => {
        const promise = sendEventAsync({ event_name: 'credential:get' } as never, undefined, 1000, 'fixture-error');
        socketReceiver.injectWireEvent('response', { request_id: 'fixture-error', error: SECRET, data: {} });
        expect(await promise).toEqual({ error: SECRET });
        expect(profilingStore.getEntries()[0].error).toBe(REDACTED_SOCKET_DATA);
        expect(logged()).not.toContain(SECRET);
    });

    it('preserves the actual socket error callback message with no diagnostic payload', async () => {
        const promise = sendEventAsync({ event_name: 'credential:get' } as never, undefined, 1000, 'fixture-socket-error');
        const error = { request_id: 'fixture-socket-error', message: SECRET, nested: { client_secret: SECRET } };
        fixture.allHandlers.get('error')!.forEach(handler => handler(error));
        expect(await promise).toEqual({ error: SECRET });
        expect(profilingStore.getEntries()[0].error).toBe(REDACTED_SOCKET_DATA);
        expect(logged()).not.toContain(SECRET);
        expect(error.nested.client_secret).toBe(SECRET);
    });

    it('correlates listener-only requests without projecting their actual response listener data', () => {
        const listener = vi.fn();
        const remove = socketReceiver.on('response', listener);
        sendEvent({ event_name: 'credential:get', request_id: 'fixture-listener', credential_data: { opaque: SECRET } } as never);
        const response = { request_id: 'fixture-listener', error: null, data: { opaque: SECRET } };
        socketReceiver.injectWireEvent('response', response);
        expect(listener).toHaveBeenCalledWith(response);
        expect(profilingStore.getEntries()[0].responseData).toBe(REDACTED_SOCKET_DATA);
        expect(logged()).not.toContain(SECRET);
        remove();
    });

    it('preserves useful known workflow results and errors in diagnostics and transport', async () => {
        const promise = sendEventAsync({ event_name: 'workflow:get', workflow_id: 'fixture-workflow', tag: 'Load workflow' } as never, undefined, 1000, 'fixture-workflow');
        socketReceiver.injectWireEvent('response', { request_id: 'fixture-workflow', error: 'Workflow unavailable', data: {} });
        expect(await promise).toEqual({ error: 'Workflow unavailable' });
        expect(profilingStore.getEntries()[0].error).toBe('Workflow unavailable');
        expect(logged()).toContain('Workflow unavailable');
        expect(profilingStore.getEntries()[0].requestData).toEqual({ event_name: 'workflow:get', workflow_id: 'fixture-workflow', tag: 'Load workflow' });
    });

    it('omits unclassified callback diagnostics even while profiling is disabled', () => {
        profilingStore.setEnabled(false);
        const callback = vi.fn();
        registerRequestCallback('fixture-unclassified', callback);
        const data = { unfamiliar: SECRET };
        socketReceiver.injectWireEvent('response', { request_id: 'fixture-unclassified', error: null, data });
        expect(callback).toHaveBeenCalledWith(data);
        expect(logged()).not.toContain(SECRET);
        expect(profilingStore.getEntries()).toEqual([]);
    });

    it('reprojects historical entry content at the read/render boundary', () => {
        profilingStore.startEvent('fixture-history', 'credential:get', { opaque: SECRET });
        // Synthetic older in-memory entry, never a real retained log.
        const internal = profilingStore as unknown as { entries: Array<Record<string, unknown>> };
        Object.assign(internal.entries[0], { requestData: { opaque: SECRET }, responseData: { opaque: SECRET }, tag: SECRET, error: SECRET });
        expect(JSON.stringify(profilingStore.getEntries())).not.toContain(SECRET);
        expect(profilingStore.getEntries()[0].error).toBe(REDACTED_SOCKET_DATA);
    });

    it('deep-copies ordinary diagnostic data and preserves binary wire bytes', () => {
        const data = { nested: { name: 'Fixture' } };
        profilingStore.startEvent('fixture-copy', 'workflow:get', data);
        data.nested.name = SECRET;
        expect(JSON.stringify(profilingStore.getEntries())).not.toContain(SECRET);
        const copy = profilingStore.getEntries()[0].requestData as { nested: { name: string } };
        copy.nested.name = SECRET;
        expect(JSON.stringify(profilingStore.getEntries())).not.toContain(SECRET);
        const bytes = new Uint8Array([0, 2, 3]);
        sendEvent({ event_name: 'yjs:sync', data: bytes } as never);
        expect(fixture.socket.emit.mock.calls[0][1]).toBe(bytes);
    });

    it('projects connection state and errors while preserving known auth codes', () => {
        fixture.socket.connected = false;
        const error = Object.assign(new Error(SECRET), { data: { message: SECRET, code: 'token_expired', opaque: SECRET } });
        fixture.handlers.get('connect_error')!(error);
        const state = socketReceiver.getConnectionState('API');
        expect(state.lastErrorCode).toBe('token_expired');
        expect(state.lastError).toBe(REDACTED_SOCKET_DATA);
        expect(state.lastDisconnectReason).toBe(REDACTED_SOCKET_DATA);
        fixture.manager.get('reconnect_error')!(error);
        fixture.handlers.get('disconnect')!(SECRET);
        expect(JSON.stringify(socketReceiver.getConnectionState('API'))).not.toContain(SECRET);
        expect(logged()).not.toContain(SECRET);
        expect(error.message).toBe(SECRET);
    });

    it('keeps auth update request and acknowledgment bytes out of diagnostics', async () => {
        const acknowledgment = { success: false, error: SECRET, message: SECRET };
        fixture.socket.emit.mockImplementation((event, _data, callback) => { if (event === 'update_auth') callback(acknowledgment); });
        expect(await socketReceiver.sendAuthUpdate()).toBe(acknowledgment);
        expect(fixture.socket.emit.mock.calls[0][1]).toEqual({ token: SECRET });
        expect(logged()).not.toContain(SECRET);
    });

    it('keeps exact known transport error diagnostics and omits arbitrary error strings', () => {
        fixture.socket.connected = false;
        fixture.handlers.get('connect_error')!(new Error('xhr poll error'));
        expect(socketReceiver.getConnectionState('API').lastError).toBe('xhr poll error');
        expect(socketReceiver.getConnectionState('API').lastErrorCode).toBeUndefined();
        expect(logged()).toContain('xhr poll error');
        fixture.handlers.get('connect_error')!(new Error(SECRET));
        expect(socketReceiver.getConnectionState('API').lastError).toBe(REDACTED_SOCKET_DATA);
        expect(logged()).not.toContain(SECRET);
    });

    it('projects actual handler/send catch diagnostics without suppressing known workflow errors', () => {
        const remove = socketReceiver.on('workflow:node:output', () => { throw new Error('Workflow unavailable'); });
        socketReceiver.injectWireEvent('workflow:node:output', { node_id: 'fixture-node' });
        expect(logged()).toContain('Workflow unavailable');
        remove();
        fixture.socket.emit.mockImplementation(() => { throw new Error(SECRET); });
        expect(sendEvent({ event_name: 'credential:get' } as never)).toBe(false);
        expect(logged()).not.toContain(SECRET);
    });
});
