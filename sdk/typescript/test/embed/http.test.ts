// The HTTP transport over a fake platform API and fake rooms: each bridge call lands on the `/v1` route it maps to with
// the page's key, and a run is followed by its room's frames, never read again but for its targets' whole outputs.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const R = vi.hoisted(() => {
  class FakeRoom {
    handlers: Record<string, Function[]> = {};
    kept: any[] = [];
    left = false;
    constructor(public name: string) {}
    on(event: string, fn: Function) { (this.handlers[event] ||= []).push(fn); return () => {}; }
    async history() { return { events: this.kept, reset: false }; }
    leave() { this.left = true; }
    /** NoClick publishes a frame: kept for history, heard live. */
    publish(event: string, data: unknown, live = true) {
      const frame = { id: String(this.kept.length + 1), event, data, from: null };
      this.kept.push(frame);
      if (live) (this.handlers.event || []).forEach((fn) => fn(frame));
    }
    status(status: string) { (this.handlers.status || []).forEach((fn) => fn(status)); }
  }
  const joined: Record<string, FakeRoom> = {};
  return { joined, FakeRoom };
});

vi.mock('../../src/room.ts', () => ({
  Room: { join: async (name: string) => (R.joined[name] = new R.FakeRoom(name)) },
}));

import { HttpTransport } from '../../src/embed/transports/http';

const WF = '11111111-2222-3333-4444-555555555555';
type Call = { method: string; path: string; query: string; body: any; auth: string | null };

let calls: Call[];
let answer: (call: Call) => unknown;

beforeEach(() => {
  calls = [];
  vi.stubGlobal('fetch', vi.fn(async (input: string, init: RequestInit = {}) => {
    const url = new URL(input);
    const headers = new Headers(init.headers);
    const call: Call = { method: init.method ?? 'GET', path: url.pathname, query: url.search,
                         body: init.body ? JSON.parse(String(init.body)) : null, auth: headers.get('authorization') };
    calls.push(call);
    const body = answer(call);
    if (body === undefined) return new Response(JSON.stringify({ error: { type: 'not_found', message: 'No such route.' } }), { status: 404 });
    return new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } });
  }));
});

afterEach(() => vi.unstubAllGlobals());

function transport() {
  const t = new HttpTransport({ url: 'https://api.test', apiKey: 'nk_live_page', workflowId: WF });
  const got: any[] = [];
  t.onMessage((m) => got.push(m));
  const ask = async (method: string, params: Record<string, unknown> = {}) => {
    t.send({ type: 'noclick:request', id: `r-${method}`, method, params });
    await vi.waitFor(() => { if (!got.some((m) => m.id === `r-${method}` && m.type === 'noclick:response')) throw new Error('waiting'); });
    return got.find((m) => m.id === `r-${method}` && m.type === 'noclick:response');
  };
  return { t, got, ask };
}

describe('HttpTransport', () => {
  it('maps the bridge calls onto the workflow\'s /v1 routes with the page\'s key', async () => {
    answer = (c) => {
      if (c.path === `/v1/workflows/${WF}/graph`) return { name: 'Leads', graph: { nodes: [{ id: 'a', type: 'form' }, { id: 'b', type: 'agent' }] } };
      if (c.path === `/v1/workflows/${WF}/edits`) return { version: 2 };
      if (c.path === `/v1/workflows/${WF}/state/count`) return { values: { count: 3 } };
      if (c.path === '/v1/workflows/tables/t1/rows') return { data: [{ id: 'r', index: 40, data: { x: 1 }, created_at: 'now' }], total_count: 41 };
      return undefined;
    };
    const { got, ask } = transport();

    expect((await ask('workflow.getInfo')).result).toEqual({ id: WF, name: 'Leads', nodeCount: 2 });
    await ask('nodes.setConfig', { nodeId: 'b', config: { prompt: 'Hi' } });
    await ask('state.set', { key: 'count', value: 3 });
    const page = (await ask('dataset.getRows', { resourceId: 't1', limit: 10, offset: 40 })).result;

    expect(calls.every((c) => c.auth === 'Bearer nk_live_page')).toBe(true);
    expect(calls.find((c) => c.path.endsWith('/edits'))!.body).toEqual({ ops: [{ op: 'update_step', id: 'b', settings: { prompt: 'Hi' } }] });
    expect(calls.find((c) => c.path.endsWith('/state/count'))).toMatchObject({ method: 'PUT', body: { value: 3 } });
    expect(got).toContainEqual({ type: 'noclick:event', event: 'state:changed', data: { key: 'count', value: 3 } });
    expect(calls.find((c) => c.path.endsWith('/rows'))!.query).toContain('cursor=40');
    expect(page).toEqual({ rows: [{ id: 'r', row_index: 40, data: { x: 1 }, created_at: 'now' }], totalCount: 41 });
  });

  it('follows a run by its room\'s frames and reads only its targets\' whole outputs at its end', async () => {
    answer = (c) => {
      if (c.method === 'POST' && c.path === `/v1/workflows/${WF}/runs`) return { id: 'op1', status: 'queued' };
      if (c.path === `/v1/workflows/${WF}/steps/b/outputs/run1`) return { output: { text: 'the whole reply' } };
      return undefined;
    };
    const { t, got } = transport();
    t.send({ type: 'noclick:request', id: 's1', method: 'execution.runNodesAndGetOutput',
             params: { runNodes: [{ id: 'a', config: { q: 2 } }], targetNodes: ['b'] } });
    await vi.waitFor(() => { if (!R.joined['run:op1']) throw new Error('waiting'); });
    const room = R.joined['run:op1'];
    // What it said before the page joined comes from its history; the rest live, and again after a reconnect.
    room.publish('workflow:started', { run_id: 'run1' }, false);
    room.publish('workflow:node:state', { run_id: 'run1', node_id: 'b', state: 'running' });
    room.status('reconnecting');
    room.publish('workflow:node:output', { run_id: 'run1', node_id: 'b', output: { text: 'cut…' } }, false);
    room.publish('workflow:node:state', { run_id: 'run1', node_id: 'b', state: 'completed' }, false);
    room.status('live');
    await vi.waitFor(() => { if (!got.some((m) => m.event === 'node:state' && m.data.state === 'completed')) throw new Error('waiting'); });
    room.publish('workflow:complete', { run_id: 'run1', status: 'succeeded', error: null });
    await vi.waitFor(() => { if (!got.some((m) => m.id === 's1' && m.event === 'done')) throw new Error('waiting'); });

    expect(calls[0].body).toEqual({ from_step: 'a', manual: { background: true, settings: { a: { q: 2 } } } });
    expect(calls.map((c) => c.path)).toEqual([`/v1/workflows/${WF}/runs`, `/v1/workflows/${WF}/steps/b/outputs/run1`]);
    expect(got.filter((m) => m.id === 's1').map((m) => [m.event, m.nodeId, m.data])).toEqual([
      ['output', 'b', { text: 'the whole reply' }], ['done', undefined, undefined],
    ]);
    expect(got.filter((m) => m.event === 'node:state').map((m) => m.data.state)).toEqual(['running', 'completed']);
    expect(got).toContainEqual({ type: 'noclick:event', event: 'node:output', data: { nodeId: 'b', output: { text: 'cut…' } } });
    expect(room.left).toBe(true);
  });

  it('hears State changes in its pages\' room and reaches none of the account\'s connections', async () => {
    answer = () => undefined;
    const { t, got, ask } = transport();
    await t.connect();
    R.joined[`page:${WF}`].publish('state:changed', { key: 'count', value: 4 });
    expect(got).toContainEqual({ type: 'noclick:event', event: 'state:changed', data: { key: 'count', value: 4 } });
    expect((await ask('auth.listCredentials')).error).toMatch(/connections/);
    expect(calls).toEqual([]);
  });
});
