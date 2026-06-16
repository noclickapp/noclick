// Pins the exact wire contract for every public API method: each call must emit
// the documented { method, params } so the host bridge / backend can service it.
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import * as nodes from '../src/core/nodes';
import * as execution from '../src/core/execution';
import * as state from '../src/core/state';
import * as auth from '../src/core/auth';
import * as workflow from '../src/core/workflow';
import * as resources from '../src/core/resources';
import * as dataset from '../src/core/dataset';
import { onInputsChanged } from '../src/inputs';
import { setTransport } from '../src/core/transport';
import { createFakeHost, type FakeHost } from './helpers/fakeHost';

let host: FakeHost;

// Set the transport ONCE for the file. These are fire-and-forget contract tests
// (assert the sent message, never reply), so they leak unsettled request promises.
// Re-calling setTransport per test would reject those leaked promises (it now
// rejects in-flight requests on swap) → unhandled rejections. One transport +
// clearing host.sent per test keeps each test isolated without a swap.
beforeAll(() => {
  host = createFakeHost();
  setTransport(host.transport);
});

beforeEach(() => {
  // Fake timers so unanswered request() promises don't leave real 30s timers ticking.
  vi.useFakeTimers();
  host.sent.length = 0;
});

afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
});

const sent = () => host.lastSent();

describe('nodes', () => {
  it('getOutput', () => {
    nodes.getOutput('n1');
    expect(sent()).toMatchObject({ type: 'noclick:request', method: 'nodes.getOutput', params: { nodeId: 'n1' } });
  });
  it('getConfig', () => {
    nodes.getConfig('n1');
    expect(sent()).toMatchObject({ method: 'nodes.getConfig', params: { nodeId: 'n1' } });
  });
  it('setConfig', () => {
    nodes.setConfig('n1', { a: 1 });
    expect(sent()).toMatchObject({ method: 'nodes.setConfig', params: { nodeId: 'n1', config: { a: 1 } } });
  });
  it('list', () => {
    nodes.list();
    expect(sent()).toMatchObject({ method: 'nodes.list', params: {} });
  });
});

describe('execution', () => {
  it('runNodesAndGetOutput serializes string and object refs', () => {
    execution.runNodesAndGetOutput(['a', { id: 'b', config: { x: 1 } }], ['a', 'b']);
    expect(sent()).toMatchObject({
      type: 'noclick:request',
      method: 'execution.runNodesAndGetOutput',
      params: { runNodes: [{ id: 'a' }, { id: 'b', config: { x: 1 } }], targetNodes: ['a', 'b'] },
    });
  });
  it('runNodesInBackground is fire-and-forget with serialized refs', () => {
    execution.runNodesInBackground(['a']);
    expect(sent()).toEqual({
      type: 'noclick:fire',
      method: 'execution.runNodesInBackground',
      params: { runNodes: [{ id: 'a' }] },
    });
  });
  it('stop sends a request', () => {
    execution.stop();
    expect(sent()).toMatchObject({ type: 'noclick:request', method: 'execution.stop', params: {} });
  });
  it('onNodeState filters push events by nodeId', () => {
    const seen: string[] = [];
    const unsub = execution.onNodeState('n1', (s) => seen.push(s));
    host.emitEvent('node:state', { nodeId: 'n1', state: 'running' });
    host.emitEvent('node:state', { nodeId: 'other', state: 'error' });
    unsub();
    host.emitEvent('node:state', { nodeId: 'n1', state: 'completed' });
    expect(seen).toEqual(['running']);
  });
  it('onNodeOutput filters push events by nodeId', () => {
    const seen: unknown[] = [];
    execution.onNodeOutput('n1', (o) => seen.push(o));
    host.emitEvent('node:output', { nodeId: 'n1', output: { tokens: 'hi' } });
    host.emitEvent('node:output', { nodeId: 'other', output: 'nope' });
    expect(seen).toEqual([{ tokens: 'hi' }]);
  });
});

describe('state', () => {
  it('get', () => {
    state.get('k');
    expect(sent()).toMatchObject({ method: 'state.get', params: { key: 'k' } });
  });
  it('get with node option', () => {
    state.get('k', { node: 'sm-1' });
    expect(sent()).toMatchObject({ method: 'state.get', params: { key: 'k', node: 'sm-1' } });
  });
  it('set', () => {
    state.set('k', { v: 1 });
    expect(sent()).toMatchObject({ method: 'state.set', params: { key: 'k', value: { v: 1 } } });
  });
  it('del maps to state.delete', () => {
    state.del('k');
    expect(sent()).toMatchObject({ method: 'state.delete', params: { key: 'k' } });
  });
  it('keys', () => {
    state.keys();
    expect(sent()).toMatchObject({ method: 'state.keys', params: {} });
  });
  it('update does a read-modify-write', async () => {
    const p = state.update<number>('counter', (cur) => (cur ?? 0) + 1);
    const getMsg = sent();
    expect(getMsg).toMatchObject({ method: 'state.get', params: { key: 'counter' } });
    host.reply(getMsg.id, 5);
    await Promise.resolve();
    await Promise.resolve();
    const setMsg = sent();
    expect(setMsg).toMatchObject({ method: 'state.set', params: { key: 'counter', value: 6 } });
    host.reply(setMsg.id, null);
    await p;
  });
  it('onChange filters state:changed events by key', () => {
    const seen: unknown[] = [];
    const unsub = state.onChange('k', (v) => seen.push(v));
    host.emitEvent('state:changed', { key: 'k', value: 1 });
    host.emitEvent('state:changed', { key: 'other', value: 2 });
    unsub();
    expect(seen).toEqual([1]);
  });
});

describe('auth', () => {
  it('hasCredential', () => {
    auth.hasCredential('github');
    expect(sent()).toMatchObject({ method: 'auth.hasCredential', params: { credentialType: 'github' } });
  });
  it('requestCredential', () => {
    auth.requestCredential('github');
    expect(sent()).toMatchObject({ method: 'auth.requestCredential', params: { credentialType: 'github' } });
  });
  it('listCredentials', () => {
    auth.listCredentials();
    expect(sent()).toMatchObject({ method: 'auth.listCredentials', params: {} });
  });
  it('createCredential', () => {
    auth.createCredential('openai', { apiKey: 'sk' }, 'My key');
    expect(sent()).toMatchObject({
      method: 'auth.createCredential',
      params: { credentialType: 'openai', data: { apiKey: 'sk' }, name: 'My key' },
    });
  });
});

describe('workflow', () => {
  it('getInfo', () => {
    workflow.getInfo();
    expect(sent()).toMatchObject({ method: 'workflow.getInfo', params: {} });
  });
});

describe('resources', () => {
  it('upload defaults resourceType to file', () => {
    resources.upload('a.png', 'image/png', 10);
    expect(sent()).toMatchObject({
      method: 'resources.upload',
      params: { name: 'a.png', mimeType: 'image/png', sizeBytes: 10, resourceType: 'file' },
    });
  });
  it('getUrl', () => {
    resources.getUrl('res-1');
    expect(sent()).toMatchObject({ method: 'resources.getUrl', params: { resourceId: 'res-1' } });
  });
  it('remove', () => {
    resources.remove('res-1');
    expect(sent()).toMatchObject({ method: 'resources.remove', params: { resourceId: 'res-1' } });
  });
  it('list omits resourceType when not given', () => {
    resources.list();
    expect(sent()).toMatchObject({ method: 'resources.list', params: {} });
  });
});

describe('dataset', () => {
  it('list', () => {
    dataset.list();
    expect(sent()).toMatchObject({ method: 'dataset.list', params: {} });
  });
  it('create', () => {
    dataset.create('Leads');
    expect(sent()).toMatchObject({ method: 'dataset.create', params: { name: 'Leads' } });
  });
  it('getRows passes pagination', () => {
    dataset.getRows('res-1', { limit: 50, offset: 100 });
    expect(sent()).toMatchObject({ method: 'dataset.getRows', params: { resourceId: 'res-1', limit: 50, offset: 100 } });
  });
  it('appendRows', () => {
    dataset.appendRows('res-1', [{ a: 1 }]);
    expect(sent()).toMatchObject({ method: 'dataset.appendRows', params: { resourceId: 'res-1', rows: [{ a: 1 }] } });
  });
  it('updateRow', () => {
    dataset.updateRow('res-1', 'row-1', { a: 2 });
    expect(sent()).toMatchObject({ method: 'dataset.updateRow', params: { resourceId: 'res-1', rowId: 'row-1', data: { a: 2 } } });
  });
  it('deleteRows', () => {
    dataset.deleteRows('res-1', ['row-1', 'row-2']);
    expect(sent()).toMatchObject({ method: 'dataset.deleteRows', params: { resourceId: 'res-1', rowIds: ['row-1', 'row-2'] } });
  });
});

describe('inputs', () => {
  it('onInputsChanged receives inputs:changed payloads until unsubscribed', () => {
    const seen: unknown[] = [];
    const unsub = onInputsChanged((i) => seen.push(i));
    host.emitEvent('inputs:changed', { q: 1 });
    unsub();
    host.emitEvent('inputs:changed', { q: 2 });
    expect(seen).toEqual([{ q: 1 }]);
  });
});
