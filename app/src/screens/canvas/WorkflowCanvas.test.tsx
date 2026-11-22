// @vitest-environment happy-dom
// The canvas this app draws on its own (WorkflowCanvas.tsx) over the platform API's answers (graph/fixtures.ts): it
// opens a workflow writing nothing, adds a step from the palette, connects steps as the workflow's rules allow, moves,
// walks, turns off, removes and brings back steps from the keyboard, saves each change as the edits that made it, and
// takes another writer's commit when the account's change stream says one landed.
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import type { Connection, Node, NodeChange } from '@xyflow/react';
import { NoClick } from 'noclick';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { ClientProvider } from '@/sdk/client';
import { createWorkLive, WorkLiveContext, type WorkLive } from '@/sdk/live';
import { fill, standing } from '@/slots';
import { graphFetch, stored, WORKFLOW } from './graph/fixtures';
import { graphRecords } from './graph/liveGraphStore';
import { V1_GRAPH_SAVES } from './graph/saves';
import { GRAPH_SAVES, STEP_DRAWING } from './slots';
import { WorkflowCanvas } from './WorkflowCanvas';

type Json = Record<string, unknown>;

interface Call {
    method: string;
    path: string;
    query: string;
    body: Json;
}

let calls: Call[] = [];
let server = stored();
let version = 4;
let readable = true;
let live: WorkLive;

// The plain drawing loads with the first step a canvas draws, and the SDK with the standards' first read: loaded once
// here, with real timers.
beforeAll(async () => {
    await import('./standardsSdk');
    const { result, unmount } = renderHook(() => standing(STEP_DRAWING).useLoaded([]));
    await waitFor(() => expect(result.current).toBe(true));
    unmount();
});

beforeEach(() => {
    vi.useFakeTimers();
    for (const id of Object.keys(graphRecords)) delete graphRecords[id];
    fill(GRAPH_SAVES, V1_GRAPH_SAVES);
    calls = [];
    server = stored();
    version = 4;
    readable = true;
    live = createWorkLive();
});

afterEach(() => {
    cleanup();
    vi.clearAllTimers();
    vi.useRealTimers();
});

const answers = graphFetch({
    server: () => server,
    version: () => version,
    edit: () => ({ version: ++version }),
});

const client = () =>
    new NoClick({
        apiKey: 'nk_test',
        baseUrl: 'https://api.test',
        maxRetries: 0,
        fetch: async (input, init) => {
            const request = new Request(input, init);
            const url = new URL(request.url);
            const text = request.method === 'GET' ? '' : await request.clone().text();
            calls.push({ method: request.method, path: url.pathname, query: url.search, body: text ? (JSON.parse(text) as Json) : {} });
            if (!readable && url.pathname.endsWith('/graph')) return Response.json({ error: { type: 'not_found', message: 'No such workflow.' } }, { status: 404 });
            return answers(request);
        },
    });

async function settle(ms = 0) {
    await act(async () => {
        await vi.advanceTimersByTimeAsync(ms);
        for (let i = 0; i < 30; i++) await Promise.resolve();
    });
}

async function draw() {
    const view = render(
        <ClientProvider client={client()}>
            <WorkLiveContext.Provider value={live}>
                <div style={{ width: 1200, height: 800 }}>
                    <WorkflowCanvas workflowId={WORKFLOW} />
                </div>
            </WorkLiveContext.Provider>
        </ClientProvider>
    );
    await settle(500);
    await settle(2500);
    return view;
}

/** What the canvas hands React Flow, read from the element React Flow draws. */
function surface(container: HTMLElement): Json {
    const el = container.querySelector('.react-flow') as Element & Record<string, unknown>;
    const key = Object.keys(el).find((k) => k.startsWith('__reactFiber'));
    let fiber = key ? (el[key] as { memoizedProps?: Json; return?: unknown } | null) : null;
    while (fiber) {
        const props = fiber.memoizedProps;
        if (props && typeof props.isValidConnection === 'function' && typeof props.onConnect === 'function') return props;
        fiber = fiber.return as typeof fiber;
    }
    throw new Error('React Flow’s props not found');
}

const call = (container: HTMLElement, name: string, ...args: unknown[]) =>
    act(() => {
        (surface(container)[name] as (...a: unknown[]) => unknown)(...args);
    });

async function key(target: Document | Window, init: KeyboardEventInit) {
    await act(() => {
        fireEvent.keyDown(target, init);
    });
    await act(() => {
        fireEvent.keyUp(target, init);
    });
}

const rec = () => graphRecords[WORKFLOW];
const ids = () => rec().nodes.map((n: Node) => n.id);
const node = (id: string) => rec().nodes.find((n: Node) => n.id === id) as Node;
const edits = () => calls.filter((c) => c.method === 'POST' && c.path === `/v1/workflows/${WORKFLOW}/edits`);
const opsOf = (call: Call) => (call.body.ops as Json[]).map((op) => op.op);

describe('the canvas on its own', () => {
    it('opens the workflow as the API reads it, writing nothing', async () => {
        const { container } = await draw();
        expect(calls.filter((c) => c.path.endsWith('/graph')).length).toBeGreaterThanOrEqual(1);
        expect(edits()).toEqual([]);
        expect(ids()).toEqual(['hook', 'agent', 'slack', 'victim']);
        expect([...container.querySelectorAll('.react-flow__node')].map((n) => n.getAttribute('data-id'))).toEqual(['hook', 'agent', 'slack', 'victim']);
        expect(rec().graphVersion).toBe(4);
    });

    it('says why when the workflow can’t be read', async () => {
        readable = false;
        await draw();
        expect(screen.getByRole('alert').textContent).toContain('couldn’t be read');
        expect(screen.queryByRole('button', { name: /add step/i })).toBeNull();
    });

    it('adds a step from the palette, found by what it’s called, and saves it', async () => {
        await draw();
        fireEvent.click(screen.getByRole('button', { name: /add step/i }));
        await settle(300);
        expect(calls.some((c) => c.path === '/v1/step_types' && c.query.includes('limit=30') && !c.query.includes('q='))).toBe(true);
        expect(screen.getAllByRole('option').map((o) => o.textContent)).toEqual(
            expect.arrayContaining([expect.stringContaining('Webhook'), expect.stringContaining('Slack')])
        );
        fireEvent.change(screen.getByRole('textbox', { name: 'Search steps' }), { target: { value: 'sla' } });
        await settle(300);
        expect(calls.some((c) => c.path === '/v1/step_types' && c.query.includes('q=sla'))).toBe(true);
        expect(screen.getAllByRole('option').map((o) => o.textContent)).toEqual([expect.stringContaining('Slack')]);
        fireEvent.keyDown(screen.getByRole('textbox', { name: 'Search steps' }), { key: 'Enter' });
        await settle();
        expect(screen.queryByRole('dialog', { name: 'Add a step' })).toBeNull();
        const added = rec().nodes.filter((n: Node) => n.type === 'automation-slack' && n.id !== 'slack');
        expect(added).toHaveLength(1);
        expect(added[0].selected).toBe(true);
        expect(added[0].id).toMatch(/^slack_[0-9a-z]{4}$/);
        await settle(2500);
        expect(edits().map(opsOf)).toEqual([['add_step']]);
        expect((edits()[0].body.ops as Json[])[0]).toMatchObject({ op: 'add_step', id: added[0].id, type: 'automation-slack' });
    });

    it('connects steps as the workflow’s rules allow, and saves the connection', async () => {
        const { container } = await draw();
        const valid = surface(container).isValidConnection as (c: Connection) => boolean;
        expect(valid({ source: 'hook', sourceHandle: null, target: 'agent', targetHandle: null })).toBe(false);
        expect(valid({ source: 'victim', sourceHandle: null, target: 'hook', targetHandle: null })).toBe(false);
        expect(valid({ source: 'victim', sourceHandle: 'top', target: 'agent', targetHandle: 'bottom' })).toBe(false);
        expect(valid({ source: 'slack', sourceHandle: 'top', target: 'agent', targetHandle: 'bottom' })).toBe(true);
        await call(container, 'onConnect', { source: 'slack', sourceHandle: 'top', target: 'agent', targetHandle: 'bottom' });
        await settle(2500);
        expect(rec().edges.map((e: { id: string }) => e.id)).toContain('xy-edge__slacktop-agentbottom');
        expect(edits().map(opsOf)).toEqual([['connect']]);
        // Wired to the agent as its tools, Slack takes no step after it.
        expect((surface(container).isValidConnection as (c: Connection) => boolean)({ source: 'slack', sourceHandle: null, target: 'victim', targetHandle: null })).toBe(false);
    });

    it('moves a step, saving only once it lands', async () => {
        const { container } = await draw();
        await call(container, 'onNodesChange', [{ type: 'position', id: 'victim', position: { x: 980, y: 40 }, dragging: true }] as NodeChange[]);
        expect(rec().dragging).toBe(true);
        await settle(2500);
        expect(edits()).toEqual([]);
        await call(container, 'onNodesChange', [{ type: 'position', id: 'victim', position: { x: 1000, y: 60 }, dragging: false }] as NodeChange[]);
        expect(rec().dragging).toBe(false);
        await settle(2500);
        expect(edits().map(opsOf)).toEqual([['move']]);
        expect(node('victim').position).toEqual({ x: 1000, y: 60 });
    });

    it('walks the steps with the arrows, turns one off, deletes one and brings it back', async () => {
        await draw();
        await key(document, { key: 'ArrowRight' });
        expect(ids().filter((id: string) => node(id).selected)).toEqual(['hook']);
        await key(document, { key: 'ArrowRight' });
        expect(ids().filter((id: string) => node(id).selected)).toEqual(['agent']);
        await key(window, { key: 'd' });
        expect((node('agent').data as Json).disabled).toBe(true);

        await key(document, { key: 'ArrowRight' });
        await key(document, { key: 'ArrowRight' });
        expect(ids().filter((id: string) => node(id).selected)).toEqual(['victim']);
        await key(document, { key: 'Backspace' });
        await settle();
        expect(ids()).not.toContain('victim');
        // The selection moves to the step beside it.
        expect(ids().filter((id: string) => node(id).selected)).toEqual(['slack']);
        expect(rec().deletedNodeIds.has('victim')).toBe(true);

        await key(window, { key: 'z', metaKey: true, ctrlKey: true });
        await settle();
        expect(ids()).toContain('victim');
        await key(window, { key: 'z', metaKey: true, ctrlKey: true, shiftKey: true });
        await settle(2500);
        expect(ids()).not.toContain('victim');
        expect(edits().flatMap(opsOf).sort()).toEqual(['remove_step', 'update_step']);
    });

    it('takes another writer’s commit when the change stream says one landed', async () => {
        await draw();
        server = { ...server, nodes: [...server.nodes, { id: 'theirs', type: 'log', position: { x: 0, y: 400 }, config: { label: 'Theirs' } }] };
        version += 1;
        act(() => live.deliver('platform:resource', { kind: 'workflow', id: WORKFLOW, status: null, parent_id: null, version }));
        await settle(2500);
        expect(ids()).toContain('theirs');
        expect(rec().graphVersion).toBe(5);
        expect(edits()).toEqual([]);
    });
});
