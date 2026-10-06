// @vitest-environment jsdom
// Exercises the production commit hook with concurrent React state and the actual Valtio graph consumer.
// Suspended/discarded/replayed renders must not grant fresh credentials until the matching placement commits.
import type { Node } from '@xyflow/react';
import { StrictMode, Suspense, startTransition, useCallback, useState } from 'react';
import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { applyNodeUpdate, createWorkflowNode, serializeNodeForSave } from '~/lib/applyNodeUpdate';

const boundary = vi.hoisted(() => ({ send: vi.fn(), get: vi.fn(), set: vi.fn(), delete: vi.fn() }));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: boundary.send, sendEvent: vi.fn(), sendEventWithCallback: vi.fn() }));
vi.mock('~/lib/socket-receiver', () => ({ onSocketEvent: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: boundary.get, set: boundary.set, delete: boundary.delete } }));
vi.mock('~/utils/credentialTypes', async () => ({ CREDENTIAL_TYPE_MAP: (await import('~/utils/credentialTypeMap')).CREDENTIAL_TYPE_MAP }));
vi.mock('~/lib/telemetry-errors', () => ({ reportInvariant: vi.fn() }));
vi.mock('~/lib/headless-builder', () => ({ headlessBuilder: { isActive: () => false } }));
vi.mock('~/lib/activeGenStore', () => ({ activeGenStore: { gens: {}, byWorkflow: {} } }));
const api = await import('~/utils/credentialAutoSelect');
const { useLiveGraph, useCommittedAutoSelectedCredentials } = await import('~/hooks/useLiveGraph');
const { graphRecords } = await import('~/lib/liveGraphStore');

const family = 'telegram_bot_token';
const workflowId = 'synthetic-committed-workflow';
const never = new Promise<void>(() => {});
let resolveResponse!: (response: { credentials: any[] }) => void;
let listResponse: Promise<{ credentials: any[] }>;
function initialNode() {
    return createWorkflowNode('new-node', 'automation-telegram', { x: 1, y: 2 }, { label: 'original', text: 'original' });
}
function authIds() {
    return boundary.send.mock.calls.map(([request]) => request)
        .filter(request => request.event_name === 'credential:authorize_for_workflow').map(request => request.credential_id);
}
async function finish() {
    const settled = api.prefetchCredentials();
    resolveResponse({ credentials: [{ id: 'fresh', name: 'fresh', credential_type: family, owned_by_me: true }] });
    await settled;
    await Promise.resolve();
    await Promise.resolve();
}
beforeEach(() => {
    api.invalidateCredentialsCache();
    api.setActiveCredentialWorkflow(null);
    delete graphRecords[workflowId];
    boundary.send.mockReset(); boundary.get.mockReset(); boundary.set.mockReset(); boundary.delete.mockReset();
    boundary.set.mockResolvedValue(undefined);
    boundary.delete.mockResolvedValue(undefined);
    listResponse = new Promise(resolve => { resolveResponse = resolve; });
    boundary.send.mockImplementation((request: any) => {
        if (request.event_name === 'credential:list') return listResponse;
        if (request.event_name === 'credential:authorize_for_workflow') return Promise.resolve({ success: true });
        throw new Error(`Unexpected synthetic event: ${request.event_name}`);
    });
});
afterEach(() => {
    cleanup();
    delete graphRecords[workflowId];
    api.invalidateCredentialsCache();
});

function stateConsumer() {
    const control = {
        nodes: [] as Node[],
        setNodes: undefined as unknown as (updater: (nodes: Node[]) => Node[]) => void,
        direct: undefined as unknown as (updater: (nodes: Node[]) => Node[]) => void,
        suspendFresh: false,
        evaluations: [] as { ids: unknown; authorizations: string[] }[],
    };
    function Consumer() {
        const [nodes, rawSetNodes] = useState(() => [initialNode()]);
        const setNodes = useCallback((updater: (nodes: Node[]) => Node[]) => {
            startTransition(() => rawSetNodes(previous => {
                const next = updater(previous);
                control.evaluations.push({ ids: next[0]?.data.credentialIds, authorizations: [...authIds()] });
                return next;
            }));
        }, []);
        useCommittedAutoSelectedCredentials(setNodes, nodes);
        control.nodes = nodes;
        control.setNodes = setNodes;
        control.direct = rawSetNodes;
        if (control.suspendFresh && (nodes[0]?.data.credentialIds as any)?.[family] === 'fresh') throw never;
        return <output data-testid="selected">{JSON.stringify(nodes.map(n => ({ type: n.type, ids: n.data.credentialIds })))}</output>;
    }
    const mounted = render(<StrictMode><Suspense fallback={<p>Pending render</p>}><Consumer /></Suspense></StrictMode>);
    return { control, mounted };
}

describe('fresh selection authorization after actual React commits', () => {
    it('emits once after an accepted committed update, including StrictMode updater replay', async () => {
        const { control } = stateConsumer();
        api.autoSelectCredentialsForNewNode(control.nodes[0], control.setNodes, workflowId);
        await act(async () => { await finish(); });
        expect(control.evaluations.length).toBeGreaterThanOrEqual(2);
        expect(control.evaluations.every(evaluation => evaluation.authorizations.length === 0)).toBe(true);
        expect(screen.getByTestId('selected').textContent).toContain('fresh');
        expect(authIds()).toEqual(['fresh']);
        await act(async () => { control.direct(nodes => nodes.map(n => applyNodeUpdate(n, { label: 'later edit' }))); });
        expect(authIds()).toEqual(['fresh']);
    });

    it('does not authorize a fresh updater whose render suspends without committing', async () => {
        const { control } = stateConsumer();
        control.suspendFresh = true;
        api.autoSelectCredentialsForNewNode(control.nodes[0], control.setNodes, workflowId);
        await act(async () => { await finish(); });
        expect(control.evaluations.some(evaluation => (evaluation.ids as any)?.[family] === 'fresh')).toBe(true);
        expect(screen.getByTestId('selected').textContent).not.toContain('fresh');
        expect(authIds()).toEqual([]);
    });

    it.each(['manual', 'changed-type', 'removed'])('does not authorize a suspended result discarded by a committed %s change', async change => {
        const { control } = stateConsumer();
        control.suspendFresh = true;
        api.autoSelectCredentialsForNewNode(control.nodes[0], control.setNodes, workflowId);
        await act(async () => { await finish(); });
        expect(authIds()).toEqual([]);
        await act(async () => {
            control.direct(nodes => change === 'removed' ? [] : nodes.map(n => change === 'manual'
                ? applyNodeUpdate(n, { credentialIds: { [family]: 'manual' } })
                : { ...n, type: 'automation-slack', data: { ...n.data, credentialIds: {} } }));
        });
        expect(screen.getByTestId('selected').textContent).not.toContain('fresh');
        expect(authIds()).toEqual([]);
    });

    it('drops an abandoned pending placement when its consumer unmounts', async () => {
        const { control, mounted } = stateConsumer();
        control.suspendFresh = true;
        api.autoSelectCredentialsForNewNode(control.nodes[0], control.setNodes, workflowId);
        await act(async () => { await finish(); });
        const discarded = control.nodes;
        mounted.unmount();
        api.authorizeCommittedAutoSelectedCredentials(control.setNodes, discarded);
        expect(authIds()).toEqual([]);
    });

    it('does not mistake a manually committed identical ID for the discarded automatic placement', async () => {
        const { control } = stateConsumer();
        control.suspendFresh = true;
        api.autoSelectCredentialsForNewNode(control.nodes[0], control.setNodes, workflowId);
        await act(async () => { await finish(); });
        control.suspendFresh = false;
        await act(async () => { control.direct(() => [applyNodeUpdate(initialNode(), { credentialIds: { [family]: 'fresh' } })]); });
        expect(screen.getByTestId('selected').textContent).toContain('fresh');
        expect(authIds()).toEqual([]);
    });

    it('does not serialize the transient placement provenance into saved nodes', async () => {
        const { control } = stateConsumer();
        api.autoSelectCredentialsForNewNode(control.nodes[0], control.setNodes, workflowId);
        await act(async () => { await finish(); });
        const saved = serializeNodeForSave(control.nodes[0]);
        expect(Object.getOwnPropertySymbols(saved)).toEqual([]);
        expect(JSON.stringify(saved)).not.toContain('autoCredentialPlacement');
        expect(JSON.stringify(saved)).not.toContain('freshCredentialPlacement');
        expect(authIds()).toEqual(['fresh']);
    });

    it('uses the actual useLiveGraph snapshot commit rather than a direct store write', async () => {
        let current!: ReturnType<typeof useLiveGraph>;
        let suspend = false;
        function Consumer() {
            const graph = useLiveGraph(workflowId, false, { initialNodes: [initialNode()] });
            current = graph;
            if (suspend && (graph.nodes[0]?.data.credentialIds as any)?.[family] === 'fresh') throw never;
            return <output data-testid="graph-selected">{JSON.stringify(graph.nodes[0]?.data.credentialIds ?? {})}</output>;
        }
        render(<Suspense fallback={<p>Pending graph render</p>}><Consumer /></Suspense>);
        api.autoSelectCredentialsForNewNode(current.nodes[0], current.setNodes, workflowId);
        suspend = true;
        await act(async () => { await finish(); });
        expect((graphRecords[workflowId].nodes[0].data.credentialIds as any)?.[family]).toBe('fresh');
        expect(authIds()).toEqual([]);
        suspend = false;
        await act(async () => { current.setNodes(nodes => nodes.map(n => applyNodeUpdate(n, { label: 'resume' }))); });
        expect(screen.getByTestId('graph-selected').textContent).toContain('fresh');
        expect(authIds()).toEqual(['fresh']);
    });
});
