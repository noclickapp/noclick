// @vitest-environment happy-dom
// The canvas this app draws on its own (WorkflowCanvas.tsx) over the platform API's answers (graph/fixtures.ts): it
// opens a workflow writing nothing, adds a step from the palette (on its own, after a step from its "+", into a
// connection from its "+"), connects steps as the workflow's rules allow, moves, walks, turns off, removes and brings
// back steps from the keyboard, copies, cuts, pastes and duplicates them, offers its right-click menus, tidies the
// layout, saves the workflow to a file and reads one back, saves each change as the edits that made it, and takes
// another writer's commit when the account's change stream says one landed.
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import type { Connection, Edge, Node, NodeChange } from '@xyflow/react';
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

/** What the canvas last put on the clipboard, which a paste from a menu reads. */
const clipboard = { text: '' };

// The plain drawing loads with the first step a canvas draws, the SDK with the standards' first read and the palette
// when it first opens: loaded once here, with real timers.
beforeAll(async () => {
    await import('./standardsSdk');
    await import('./surface/StepPalette');
    Object.defineProperty(navigator, 'clipboard', {
        configurable: true,
        value: { writeText: async (text: string) => void (clipboard.text = text), readText: async () => clipboard.text },
    });
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
    clipboard.text = '';
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

const say = (name: string, detail: Json) =>
    act(() => {
        document.dispatchEvent(new CustomEvent(name, { detail }));
    });

const at = (x: number, y: number) => ({ clientX: x, clientY: y, preventDefault: () => undefined, stopPropagation: () => undefined });

/** The right-click menu's choices as drawn. */
const menu = () => [...document.querySelectorAll('[role="menu"] [role="menuitem"]')].map((item) => item.textContent);

async function choose(label: string) {
    const item = [...document.querySelectorAll('[role="menu"] [role="menuitem"]')].find((el) => el.textContent === label);
    if (!item) throw new Error(`the menu has no “${label}”: ${JSON.stringify(menu())}`);
    await act(async () => {
        fireEvent.click(item);
    });
    await settle();
}

const select = (container: HTMLElement, chosen: string[]) =>
    call(
        container,
        'onNodesChange',
        rec().nodes.map((n: Node) => ({ type: 'select', id: n.id, selected: chosen.includes(n.id) }))
    );

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

    it('adds a step after another from its “+”, and into a connection from its “+”', async () => {
        await draw();
        // A step's "+": the palette opens, and the pick lands after the step, connected to it.
        await say('noclick:open-flow-helper-from-node', { nodeId: 'victim', handleId: null, handlePosition: 'right', offsetFromCenter: 0 });
        await settle(300);
        expect(screen.getByRole('dialog', { name: 'Add a step' })).toBeTruthy();
        fireEvent.change(screen.getByRole('textbox', { name: 'Search steps' }), { target: { value: 'log' } });
        await settle(300);
        fireEvent.keyDown(screen.getByRole('textbox', { name: 'Search steps' }), { key: 'Enter' });
        await settle();
        expect(screen.queryByRole('dialog', { name: 'Add a step' })).toBeNull();
        const after = rec().nodes.find((n: Node) => n.type === 'log' && n.id !== 'victim') as Node;
        expect(after.selected).toBe(true);
        expect(after.position).toEqual({ x: node('victim').position.x + 90 + 130, y: node('victim').position.y });
        expect(rec().edges.some((e: Edge) => e.source === 'victim' && e.target === after.id)).toBe(true);

        // A connection's "+": the pick is spliced in, and what follows moves along to make room.
        const slackWas = node('slack').position.x;
        await say('noclick:insert-node-on-edge', { edgeId: 'agent-slack', source: 'agent', target: 'slack', sourceHandle: null, targetHandle: null, position: { x: 500, y: 45 } });
        await settle(300);
        fireEvent.change(screen.getByRole('textbox', { name: 'Search steps' }), { target: { value: 'log' } });
        await settle(300);
        fireEvent.keyDown(screen.getByRole('textbox', { name: 'Search steps' }), { key: 'Enter' });
        await settle();
        const between = rec().nodes.find((n: Node) => n.type === 'log' && n.id !== 'victim' && n.id !== after.id) as Node;
        expect(rec().edges.some((e: Edge) => e.id === 'agent-slack')).toBe(false);
        expect(rec().edges.some((e: Edge) => e.source === 'agent' && e.target === between.id)).toBe(true);
        expect(rec().edges.some((e: Edge) => e.source === between.id && e.target === 'slack')).toBe(true);
        expect(node('slack').position.x).toBeGreaterThan(slackWas);

        await settle(2500);
        expect(edits().flatMap(opsOf).sort()).toEqual(['add_step', 'add_step', 'connect', 'connect', 'connect', 'disconnect', 'move']);

        // Each add is one step back.
        await key(window, { key: 'z', metaKey: true, ctrlKey: true });
        await settle();
        expect(ids()).not.toContain(between.id);
        expect(ids()).toContain(after.id);
    });

    it('forgets the step a pick was for once the palette closes', async () => {
        await draw();
        await say('noclick:open-flow-helper-from-node', { nodeId: 'victim', handleId: null, handlePosition: 'right', offsetFromCenter: 0 });
        await settle(300);
        fireEvent.click(screen.getByRole('button', { name: 'Close' }));
        await settle();
        await say('noclick:add-connected-node', { nodeType: 'log' });
        await settle();
        const added = rec().nodes.find((n: Node) => n.type === 'log' && n.id !== 'victim') as Node;
        expect(rec().edges.some((e: Edge) => e.target === added.id)).toBe(false);
    });

    it('copies steps without their secrets, and pastes them as new steps that keep their accounts', async () => {
        const { container } = await draw();
        // Typed this session: a key and a request's Authorization header.
        await call(container, 'onNodesChange', [
            { type: 'replace', id: 'agent', item: { ...node('agent'), data: { ...node('agent').data, config: { ...(node('agent').data.config as Json), api_key: 'typed key', headers: [{ key: 'Authorization', value: 'Bearer typed' }, { key: 'Accept', value: 'text/plain' }] } } } },
        ] as NodeChange[]);
        await select(container, ['agent', 'slack']);
        await act(async () => {
            window.dispatchEvent(new Event('copy', { bubbles: true, cancelable: true }));
            await Promise.resolve();
        });
        expect(clipboard.text).not.toContain('typed key');
        expect(clipboard.text).not.toContain('Bearer typed');
        const copied = JSON.parse(clipboard.text) as { nodes: Array<{ id: string; config: Json }>; edges: Json[] };
        expect(copied.nodes.map((n) => n.id)).toEqual(['agent', 'slack']);
        expect(copied.edges).toHaveLength(1);
        expect(copied.nodes[0].config).toMatchObject({
            label: 'Agent',
            model: 'openai/gpt-5',
            credentialIds: { agent_openai: 'cred_openai' },
            headers: [{ key: 'Authorization' }, { key: 'Accept', value: 'text/plain' }],
        });
        expect(copied.nodes[0].config).not.toHaveProperty('api_key');

        // Pasted from the canvas's menu, where it was clicked.
        await call(container, 'onPaneContextMenu', at(700, 500));
        expect(menu()).toEqual(['Add node', 'Add sticky note', 'Paste', 'Select all', 'Auto-layout', 'Fit view', 'Import from a file', 'Export to a file']);
        await choose('Paste');
        await settle();
        expect(ids()).toHaveLength(6);
        const [agentCopy, slackCopy] = rec().nodes.slice(4) as Node[];
        expect(agentCopy.type).toBe('agent');
        expect(agentCopy.id).not.toBe('agent');
        expect((agentCopy.data as Json).credentialIds).toEqual({ agent_openai: 'cred_openai' });
        expect(JSON.stringify(agentCopy.data)).not.toContain('typed');
        expect(rec().edges.some((e: Edge) => e.source === agentCopy.id && e.target === slackCopy.id)).toBe(true);

        // One step back takes the paste away.
        await key(window, { key: 'z', metaKey: true, ctrlKey: true });
        await settle();
        expect(ids()).toHaveLength(4);
    });

    it('leaves a paste alone while a field is typed in, and text that holds no workflow', async () => {
        await draw();
        const paste = (text: string) =>
            act(() => {
                const event = new Event('paste', { bubbles: true, cancelable: true });
                Object.assign(event, { clipboardData: { getData: () => text } });
                window.dispatchEvent(event);
            });
        await paste('just some words');
        const field = document.createElement('input');
        document.body.appendChild(field);
        field.focus();
        await paste(JSON.stringify({ type: 'noclick-workflow', nodes: [{ id: 'a', type: 'log', position: { x: 0, y: 0 }, config: {} }], edges: [] }));
        field.remove();
        await settle();
        expect(ids()).toHaveLength(4);
    });

    it('duplicates, cuts, turns off and deletes steps from their menus, and adds a note from the canvas’s', async () => {
        const { container } = await draw();
        await call(container, 'onNodeContextMenu', at(400, 300), node('slack'));
        // No panel and no runs here yet: a step's menu offers neither.
        expect(menu()).toEqual(['Duplicate', 'Copy', 'Cut', 'Disable', 'Rename', 'Delete']);
        await choose('Duplicate');
        const twin = rec().nodes.find((n: Node) => n.type === 'automation-slack' && n.id !== 'slack') as Node;
        expect(twin.position).toEqual({ x: node('slack').position.x + 40, y: node('slack').position.y + 40 });
        expect((twin.data as Json).credentialIds).toEqual({ slack_oauth: 'cred_slack' });

        await call(container, 'onNodeContextMenu', at(420, 320), node('slack'));
        await choose('Disable');
        expect((node('slack').data as Json).disabled).toBe(true);

        await call(container, 'onNodeContextMenu', at(440, 340), node('victim'));
        await choose('Cut');
        await settle();
        expect(ids()).not.toContain('victim');
        expect(JSON.parse(clipboard.text).nodes.map((n: Json) => n.id)).toEqual(['victim']);

        await call(container, 'onSelectionContextMenu', at(460, 360), [node('hook'), node('agent')]);
        expect(menu()).toEqual(['Duplicate (2)', 'Copy (2)', 'Cut (2)', 'Disable (2)', 'Delete (2)']);
        await choose('Delete (2)');
        expect(ids()).not.toContain('hook');
        expect(ids()).not.toContain('agent');
        expect(rec().edges).toHaveLength(0);

        await call(container, 'onPaneContextMenu', at(300, 200));
        await choose('Add sticky note');
        expect(rec().nodes.some((n: Node) => n.type === 'stickyNote')).toBe(true);

        await settle(2500);
        // Each change saves as its edit: the three steps removed, the twin added with its account by its id, the note
        // added, the step turned off.
        const saved = edits().flatMap((e) => e.body.ops as Json[]);
        expect(saved.filter((op) => op.op === 'remove_step').map((op) => op.id).sort()).toEqual(['agent', 'hook', 'victim']);
        expect([...new Set(saved.map((op) => op.op))].sort()).toEqual(['add_note', 'add_step', 'move', 'remove_step', 'set_connection', 'update_step']);
        expect(saved.find((op) => op.op === 'set_connection')).toMatchObject({ id: twin.id, connection: 'cred_slack', slot: 'slack_oauth' });
        expect(JSON.stringify(edits().map((e) => e.body))).not.toContain('cred_openai');
    });

    it('tidies the layout as one step back, and says when there’s nothing to move', async () => {
        await draw();
        const places = () => Object.fromEntries(rec().nodes.map((n: Node) => [n.id, n.position]));
        const opened = places();
        fireEvent.click(screen.getByRole('button', { name: /tidy up/i }));
        await settle();
        const tidied = places();
        expect(tidied).not.toEqual(opened);
        // Left to right in the order the workflow runs.
        expect(tidied.hook.x).toBeLessThan(tidied.agent.x);
        expect(tidied.agent.x).toBeLessThan(tidied.slack.x);
        fireEvent.click(screen.getByRole('button', { name: /tidy up/i }));
        await settle();
        expect(places()).toEqual(tidied);
        await key(window, { key: 'z', metaKey: true, ctrlKey: true });
        await settle();
        expect(places()).toEqual(opened);
        await settle(2500);
        expect(edits().flatMap(opsOf).every((op) => op === 'move')).toBe(true);
    });

    it('saves the workflow to a file without its secrets and reads one back as new steps', async () => {
        const { container } = await draw();
        const saved: Array<{ name: string; text: Promise<string> }> = [];
        const blobs = new Map<string, Blob>();
        vi.spyOn(URL, 'createObjectURL').mockImplementation((blob) => {
            const url = `blob:test/${blobs.size}`;
            blobs.set(url, blob as Blob);
            return url;
        });
        vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined);
        vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
            const blob = blobs.get(this.href);
            if (blob) saved.push({ name: this.download, text: blob.text() });
        });
        await call(container, 'onNodesChange', [
            { type: 'replace', id: 'hook', item: { ...node('hook'), data: { ...node('hook').data, config: { ...(node('hook').data.config as Json), signing_secret: 'typed secret' } } } },
        ] as NodeChange[]);

        await call(container, 'onPaneContextMenu', at(300, 200));
        await choose('Export to a file');
        expect(saved).toHaveLength(1);
        expect(saved[0].name).toBe('workflow.json');
        vi.useRealTimers();
        const text = await saved[0].text;
        expect(text).not.toContain('typed secret');
        const file = JSON.parse(text) as { workflow_data: { nodes: Json[]; edges: Json[] } };
        expect(file.workflow_data.nodes.map((n) => n.id)).toEqual(['hook', 'agent', 'slack', 'victim']);
        expect(file.workflow_data.edges).toHaveLength(2);

        const input = container.querySelector('input[type="file"]') as HTMLInputElement;
        const read = async (picked: File) => {
            await act(async () => {
                fireEvent.change(input, { target: { files: [picked] } });
            });
            await waitFor(() => expect(input.value).toBe(''));
        };
        await read(new File([text], 'orders.json', { type: 'application/json' }));
        await waitFor(() => expect(ids()).toHaveLength(8));
        expect(new Set(ids()).size).toBe(8);
        expect(rec().edges).toHaveLength(4);

        // A file that holds no workflow changes nothing.
        await read(new File(['{"hello":"world"}'], 'other.json', { type: 'application/json' }));
        expect(ids()).toHaveLength(8);
        vi.restoreAllMocks();
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
