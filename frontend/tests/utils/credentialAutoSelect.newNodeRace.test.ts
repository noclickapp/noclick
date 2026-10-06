// Exercises the real new-node selector with a deferred credential:list response and actual node updates.
// State edits and deferred/replayed setNodes callbacks reproduce the race without accounts, sockets, or IndexedDB.
import type { Node } from '@xyflow/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import telegramSchema from '~/schemas/nodes/telegram.json';
import { applyNodeUpdate, createWorkflowNode } from '~/lib/applyNodeUpdate';

const boundary = vi.hoisted(() => ({ send: vi.fn(), get: vi.fn(), set: vi.fn(), delete: vi.fn() }));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: boundary.send }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: boundary.get, set: boundary.set, delete: boundary.delete } }));
// Keep the production mapping while isolating unrelated service-icon/metadata consumers.
vi.mock('~/utils/credentialTypes', async () => ({ CREDENTIAL_TYPE_MAP: (await import('~/utils/credentialTypeMap')).CREDENTIAL_TYPE_MAP }));
vi.mock('~/lib/telemetry-errors', () => ({ reportInvariant: vi.fn() }));
const api = await import('~/utils/credentialAutoSelect');

const family = 'telegram_bot_token';
const nodeType = 'automation-telegram';
const workflowId = 'synthetic-workflow';
const originalCredentialProperty = telegramSchema.properties.credentials;
const schemaSlot: any = telegramSchema;
type Updater = (previous: Node[]) => Node[];
function deferred<T>() {
    let resolve!: (value: T) => void;
    let reject!: (reason: unknown) => void;
    const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
    return { promise, resolve, reject };
}
let response: ReturnType<typeof deferred<{ credentials: any[] }>>;

beforeEach(() => {
    api.invalidateCredentialsCache();
    api.setActiveCredentialWorkflow(null);
    boundary.send.mockReset(); boundary.get.mockReset(); boundary.set.mockReset(); boundary.delete.mockReset();
    boundary.set.mockResolvedValue(undefined);
    boundary.delete.mockResolvedValue(undefined);
    response = deferred();
    boundary.send.mockImplementation((request: any) => {
        if (request.event_name === 'credential:list') return response.promise;
        if (request.event_name === 'credential:authorize_for_workflow') return Promise.resolve({ success: true });
        throw new Error(`Unexpected synthetic socket event: ${request.event_name}`);
    });
});
afterEach(() => {
    schemaSlot.properties.credentials = originalCredentialProperty;
    api.invalidateCredentialsCache();
    api.setActiveCredentialWorkflow(null);
    vi.restoreAllMocks();
});

function credential(id: string, extra: Record<string, unknown> = {}) {
    return { id, name: id, credential_type: family, owned_by_me: true, updated_at: '2026-01-01T00:00:00Z', ...extra };
}
function seed(id = 'cached', extra: Record<string, unknown> = {}) {
    api.upsertCredentialsIntoCache([credential(id, extra)]);
}
function newNode(ids?: Record<string, string>) {
    return createWorkflowNode('new-node', nodeType, { x: 12, y: 34 }, {
        label: 'Synthetic node', operation: 'get_me', credentialIds: ids,
        config: { text: 'original', _settings: { onError: 'stop' } },
    });
}
function state(initial = newNode(), queued = false) {
    let nodes = [initial, createWorkflowNode('other-node', 'stickyNote', { x: 1, y: 2 }, { content: 'unchanged' })];
    const pending: Updater[] = [];
    const setter = vi.fn((updater: Updater) => {
        if (queued) pending.push(updater);
        else {
            nodes = updater(nodes);
            api.authorizeCommittedAutoSelectedCredentials(setter, nodes);
        }
    });
    return {
        setter, pending,
        get nodes() { return nodes; },
        replace(next: Node[]) { nodes = next; },
        edit(update: Parameters<typeof applyNodeUpdate>[1]) { nodes = nodes.map(n => n.id === initial.id ? applyNodeUpdate(n, update) : n); },
        flush() {
            while (pending.length) nodes = pending.shift()!(nodes);
            api.authorizeCommittedAutoSelectedCredentials(setter, nodes);
        },
    };
}
function authorizations() {
    return boundary.send.mock.calls.map(([request]) => request)
        .filter(request => request.event_name === 'credential:authorize_for_workflow')
        .map(request => ({ workflow_id: request.workflow_id, credential_id: request.credential_id }));
}
function listRequests() {
    return boundary.send.mock.calls.filter(([request]) => request.event_name === 'credential:list');
}
async function finish(rows = [credential('fresh')]) {
    // Await the real cache-fetch chain shared with autoSelectCredential, then its placement callback.
    const settled = api.prefetchCredentials();
    response.resolve({ credentials: rows });
    await settled;
    await Promise.resolve();
    await Promise.resolve();
}

describe('new-node background selection applies against current state', () => {
    it('places and authorizes a healthy fresh selection when the initially empty node is unchanged', async () => {
        const s = state();
        const originalOther = s.nodes[1];
        api.autoSelectCredentialsForNewNode(s.nodes[0], s.setter, workflowId);
        expect(s.setter).not.toHaveBeenCalled();
        expect(listRequests()).toHaveLength(1);
        await finish();
        expect(s.nodes[0].data.credentialIds).toEqual({ [family]: 'fresh' });
        expect(s.nodes[1]).toBe(originalOther);
        expect(authorizations()).toEqual([{ workflow_id: workflowId, credential_id: 'fresh' }]);
    });

    it('places cached credentials immediately and replaces them with fresh credentials if unchanged', async () => {
        seed();
        const s = state();
        api.autoSelectCredentialsForNewNode(s.nodes[0], s.setter, workflowId);
        expect(s.nodes[0].data.credentialIds).toEqual({ [family]: 'cached' });
        expect(authorizations()).toEqual([{ workflow_id: workflowId, credential_id: 'cached' }]);
        await finish();
        expect(s.nodes[0].data.credentialIds).toEqual({ [family]: 'fresh' });
        expect(authorizations()).toEqual([
            { workflow_id: workflowId, credential_id: 'cached' },
            { workflow_id: workflowId, credential_id: 'fresh' },
        ]);
    });

    it('preserves the initial manual/import credential fast path without fetching or updating', () => {
        seed();
        const ids = { [family]: 'manual', other_family: 'other-manual' };
        const s = state(newNode(ids));
        api.autoSelectCredentialsForNewNode(s.nodes[0], s.setter, workflowId);
        expect(s.nodes[0].data.credentialIds).toEqual(ids);
        expect(s.setter).not.toHaveBeenCalled();
        expect(listRequests()).toHaveLength(0);
        expect(authorizations()).toEqual([
            { workflow_id: workflowId, credential_id: 'manual' },
            { workflow_id: workflowId, credential_id: 'other-manual' },
        ]);
    });

    it.each([false, true])('keeps an intervening manual choice with cache populated=%s', async cached => {
        if (cached) seed();
        const s = state();
        api.autoSelectCredentialsForNewNode(s.nodes[0], s.setter, workflowId);
        s.edit({ credentialIds: { [family]: 'manual' } });
        const edited = s.nodes;
        await finish();
        expect(s.nodes).toBe(edited);
        expect(s.nodes[0].data.credentialIds).toEqual({ [family]: 'manual' });
        expect(authorizations().map(a => a.credential_id)).toEqual(cached ? ['cached'] : []);
    });

    it.each([false, true])('does not restore a removed node or authorize fresh credentials with cache populated=%s', async cached => {
        if (cached) seed();
        const s = state();
        api.autoSelectCredentialsForNewNode(s.nodes[0], s.setter, workflowId);
        s.replace(s.nodes.filter(n => n.id !== 'new-node'));
        const removed = s.nodes;
        await finish();
        expect(s.nodes).toBe(removed);
        expect(s.nodes.map(n => n.id)).toEqual(['other-node']);
        expect(authorizations().map(a => a.credential_id)).toEqual(cached ? ['cached'] : []);
    });

    it.each([false, true])('does not apply to a same-ID node of a changed type with cache populated=%s', async cached => {
        if (cached) seed();
        const s = state();
        api.autoSelectCredentialsForNewNode(s.nodes[0], s.setter, workflowId);
        s.replace(s.nodes.map(n => n.id === 'new-node' ? { ...n, type: 'automation-slack' } : n));
        const changed = s.nodes;
        await finish();
        expect(s.nodes).toBe(changed);
        expect(s.nodes[0].type).toBe('automation-slack');
        expect(authorizations().map(a => a.credential_id)).toEqual(cached ? ['cached'] : []);
    });

    it.each([
        {}, { [family]: 'cached', other_family: 'manual' }, { other_family: 'cached' }, { [family]: 'manual' },
    ])('rejects a changed cached selection map %j', async ids => {
        seed();
        const s = state();
        api.autoSelectCredentialsForNewNode(s.nodes[0], s.setter, workflowId);
        s.edit({ credentialIds: ids });
        const changed = s.nodes;
        await finish();
        expect(s.nodes).toBe(changed);
        expect(authorizations().map(a => a.credential_id)).toEqual(['cached']);
    });

    it('compares a snapshot when the cached map is mutated in place', async () => {
        seed();
        const s = state();
        api.autoSelectCredentialsForNewNode(s.nodes[0], s.setter, workflowId);
        (s.nodes[0].data.credentialIds as Record<string, string>)[family] = 'manual-in-place';
        const changed = s.nodes;
        await finish();
        expect(s.nodes).toBe(changed);
        expect(s.nodes[0].data.credentialIds).toEqual({ [family]: 'manual-in-place' });
        expect(authorizations().map(a => a.credential_id)).toEqual(['cached']);
    });

    it('accepts an equivalent cloned map and preserves subsequent config/metadata edits', async () => {
        seed();
        const s = state();
        api.autoSelectCredentialsForNewNode(s.nodes[0], s.setter, workflowId);
        s.edit({ credentialIds: { [family]: 'cached' }, label: 'Edited label', config: { text: 'edited' } });
        const config = s.nodes[0].data.config;
        await finish();
        expect(s.nodes[0].data.credentialIds).toEqual({ [family]: 'fresh' });
        expect(s.nodes[0].data.label).toBe('Edited label');
        expect(s.nodes[0].data.config).toEqual(config);
        expect((s.nodes[0].data.config as any).text).toBe('edited');
        expect((s.nodes[0].data.config as any)._settings).toEqual({ onError: 'stop' });
    });

    it.each([undefined, null, {}])('treats a current nullish/empty selection as unchanged after an empty start: %j', async ids => {
        const s = state();
        api.autoSelectCredentialsForNewNode(s.nodes[0], s.setter, workflowId);
        s.replace(s.nodes.map(n => n.id === 'new-node' ? { ...n, data: { ...n.data, credentialIds: ids } } : n));
        await finish();
        expect(s.nodes[0].data.credentialIds).toEqual({ [family]: 'fresh' });
        expect(authorizations().map(a => a.credential_id)).toEqual(['fresh']);
    });

    it.each([[], '', false])('does not overwrite a malformed/non-record current selection %j', async ids => {
        const s = state();
        api.autoSelectCredentialsForNewNode(s.nodes[0], s.setter, workflowId);
        s.replace(s.nodes.map(n => n.id === 'new-node' ? { ...n, data: { ...n.data, credentialIds: ids } } : n));
        const changed = s.nodes;
        await finish();
        expect(s.nodes).toBe(changed);
        expect(authorizations()).toEqual([]);
    });

    it('does not update or authorize again when fresh selection equals cached selection', async () => {
        seed();
        const s = state();
        api.autoSelectCredentialsForNewNode(s.nodes[0], s.setter, workflowId);
        await finish([credential('cached')]);
        expect(s.setter).toHaveBeenCalledTimes(1);
        expect(authorizations().map(a => a.credential_id)).toEqual(['cached']);
    });

    it.each([false, true])('keeps the prior state when the fresh list is empty, cached=%s', async cached => {
        if (cached) seed();
        const s = state();
        api.autoSelectCredentialsForNewNode(s.nodes[0], s.setter, workflowId);
        const before = s.nodes;
        await finish([]);
        expect(s.nodes).toBe(before);
        expect(authorizations().map(a => a.credential_id)).toEqual(cached ? ['cached'] : []);
    });

    it('uses the existing healthy preference instead of a newer dead credential', async () => {
        const s = state();
        api.autoSelectCredentialsForNewNode(s.nodes[0], s.setter, workflowId);
        await finish([
            credential('dead-newer', { updated_at: '2026-02-01T00:00:00Z', connection_healthy: false }),
            credential('healthy-older'),
        ]);
        expect(s.nodes[0].data.credentialIds).toEqual({ [family]: 'healthy-older' });
        expect(authorizations().map(a => a.credential_id)).toEqual(['healthy-older']);
    });

    it('preserves the existing dead-only fallback', async () => {
        const s = state();
        api.autoSelectCredentialsForNewNode(s.nodes[0], s.setter, workflowId);
        await finish([credential('dead-only', { revoked_at: '2026-02-01T00:00:00Z' })]);
        expect(s.nodes[0].data.credentialIds).toEqual({ [family]: 'dead-only' });
        expect(authorizations().map(a => a.credential_id)).toEqual(['dead-only']);
    });

    it('uses the existing active-workflow fallback for an accepted placement', async () => {
        api.setActiveCredentialWorkflow('active-workflow');
        const s = state();
        api.autoSelectCredentialsForNewNode(s.nodes[0], s.setter);
        await finish();
        expect(authorizations()).toEqual([{ workflow_id: 'active-workflow', credential_id: 'fresh' }]);
    });

    it('does not emit authorization without a workflow but still attaches a valid selection', async () => {
        const s = state();
        api.autoSelectCredentialsForNewNode(s.nodes[0], s.setter);
        await finish();
        expect(s.nodes[0].data.credentialIds).toEqual({ [family]: 'fresh' });
        expect(authorizations()).toEqual([]);
    });

    it('validates when a deferred updater actually runs and never authorizes a skipped result', async () => {
        const s = state(newNode(), true);
        api.autoSelectCredentialsForNewNode(s.nodes[0], s.setter, workflowId);
        await finish();
        expect(s.pending).toHaveLength(1);
        expect(authorizations()).toEqual([]);
        s.edit({ credentialIds: { [family]: 'manual-after-fetch' } });
        const changed = s.nodes;
        s.flush();
        expect(s.nodes).toBe(changed);
        expect(authorizations()).toEqual([]);
    });

    it.each(['removed', 'changed-type'])('rejects a deferred updater after the node is %s following fetch completion', async change => {
        const s = state(newNode(), true);
        api.autoSelectCredentialsForNewNode(s.nodes[0], s.setter, workflowId);
        await finish();
        expect(s.pending).toHaveLength(1);
        expect(authorizations()).toEqual([]);
        s.replace(change === 'removed'
            ? s.nodes.filter(n => n.id !== 'new-node')
            : s.nodes.map(n => n.id === 'new-node' ? { ...n, type: 'automation-slack' } : n));
        const changed = s.nodes;
        s.flush();
        expect(s.nodes).toBe(changed);
        expect(authorizations()).toEqual([]);
    });

    it('captures the original node ID if a caller mutates the original node object', async () => {
        const s = state();
        api.autoSelectCredentialsForNewNode(s.nodes[0], s.setter, workflowId);
        s.nodes[0].id = 'renamed-node';
        const changed = s.nodes;
        await finish();
        expect(s.nodes).toBe(changed);
        expect(s.nodes[0].id).toBe('renamed-node');
        expect(authorizations()).toEqual([]);
    });

    it('authorizes only once when an accepted updater is replayed against the same prior state', async () => {
        const s = state(newNode(), true);
        api.autoSelectCredentialsForNewNode(s.nodes[0], s.setter, workflowId);
        await finish();
        const updater = s.pending[0];
        const prior = s.nodes;
        const committed = updater(prior);
        expect(committed[0].data.credentialIds).toEqual({ [family]: 'fresh' });
        expect(updater(prior)[0].data.credentialIds).toEqual({ [family]: 'fresh' });
        expect(authorizations()).toEqual([]);
        api.authorizeCommittedAutoSelectedCredentials(s.setter, committed);
        api.authorizeCommittedAutoSelectedCredentials(s.setter, committed);
        expect(authorizations().map(a => a.credential_id)).toEqual(['fresh']);
    });

    it('preserves the exact nullable/discriminated leaf dependency in the actual selector path', async () => {
        schemaSlot.properties.credentials = { anyOf: [
            { type: 'null' },
            { oneOf: [{ $ref: '#/$defs/TelegramBotTokenCredential' }], discriminator: { propertyName: 'credential_type' } },
        ] };
        seed();
        const s = state();
        api.autoSelectCredentialsForNewNode(s.nodes[0], s.setter, workflowId);
        expect(s.nodes[0].data.credentialIds).toEqual({ [family]: 'cached' });
        await finish();
        expect(s.nodes[0].data.credentialIds).toEqual({ [family]: 'fresh' });
        expect(authorizations().map(a => a.credential_id)).toEqual(['cached', 'fresh']);
    });

    it('does nothing for a node without a credential schema', async () => {
        const s = state(createWorkflowNode('new-node', 'stickyNote', { x: 0, y: 0 }, { content: 'note' }));
        const before = s.nodes;
        api.autoSelectCredentialsForNewNode(s.nodes[0], s.setter, workflowId);
        await Promise.resolve();
        expect(s.nodes).toBe(before);
        expect(s.setter).not.toHaveBeenCalled();
        expect(boundary.send).not.toHaveBeenCalled();
    });
});
