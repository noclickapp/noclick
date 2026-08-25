/**
 * Tests for applyAgenticGraphEvent — the cross-channel mirror that pulls
 * builder mutations into the canvas state when the canvas is unmounted (or
 * before its per-gen subscription is attached).
 *
 * Why this exists as a regression suite: this function was the SILENT drop
 * point in the credential-set bug. node_added/edge_added events arrive
 * with the full node/edge under a NESTED key (event.node / event.edge),
 * but the old handler only read flat fields (event.nodeId / event.edgeId)
 * and early-returned. Likewise node_updated only applied the label and
 * mcpAnimationState, throwing away credentialIds, config field changes,
 * and disabled-flag toggles. When the user clicks a credential picker
 * while the canvas isn't mounted, the only surviving signal arrives on
 * the active_gen:graph_event channel — if it drops the payload, the
 * autosave persists a workflow with no credentials and the next run_node
 * fails with "Credentials are required."
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';

// liveGraphStore registers socket listeners at module load. Stub them
// out so the test doesn't pull in the real socket runtime.
vi.mock('~/lib/socket-sender', () => ({
    sendEvent: vi.fn(),
    sendEventWithCallback: vi.fn(() => () => {}),
}));
vi.mock('~/lib/socket-receiver', () => ({
    onSocketEvent: vi.fn(() => () => {}),
}));
vi.mock('~/lib/headless-builder', () => ({
    headlessBuilder: { isActive: vi.fn(() => false) },
}));
vi.mock('~/lib/activeGenStore', () => ({
    activeGenStore: { gens: {}, byWorkflow: {} },
}));

import {
    applyAgenticGraphEvent,
    graphRecords,
} from './liveGraphStore';

const WORKFLOW_ID = 'wf-test-1';

function getNode(id: string) {
    return graphRecords[WORKFLOW_ID]?.nodes.find(n => n.id === id);
}

function nodeData(id: string) {
    return getNode(id)?.data as Record<string, any> | undefined;
}

describe('applyAgenticGraphEvent', () => {
    beforeEach(() => {
        // Reset the global record so tests don't leak state.
        for (const k of Object.keys(graphRecords)) delete graphRecords[k];
    });

    describe('node_added (nested shape)', () => {
        it('creates a node from the nested {node: {…}} payload', () => {
            // Shape emitted by AgenticBuilder via NodeState.to_dict — id/type/label
            // live under `event.node`, NOT at the top of the event.
            applyAgenticGraphEvent(WORKFLOW_ID, {
                type: 'node_added',
                node: {
                    id: 'slack_fetch',
                    type: 'automation-slack',
                    label: 'Fetch Slack Messages',
                    goal: 'pull messages',
                    operation: 'get_channel_messages',
                    config: { channel: 'C123' },
                    position: { x: 500, y: 300 },
                },
            } as any);

            const node = getNode('slack_fetch');
            expect(node).toBeDefined();
            expect(node!.type).toBe('automation-slack');
            // Position from the event, not the staggered-grid fallback
            expect(node!.position).toEqual({ x: 500, y: 300 });
            // Real config field landed in data.config
            expect(node!.data.config).toMatchObject({ channel: 'C123' });
            // Top-level metadata routed correctly
            expect(node!.data.operation).toBe('get_channel_messages');
            expect(node!.data.label).toBe('Fetch Slack Messages');
            expect(node!.data.goal).toBe('pull messages');
        });

        it('idempotent on duplicate id', () => {
            const event = {
                type: 'node_added',
                node: { id: 'n1', type: 'agent', label: 'A' },
            } as any;
            applyAgenticGraphEvent(WORKFLOW_ID, event);
            applyAgenticGraphEvent(WORKFLOW_ID, event);
            expect(graphRecords[WORKFLOW_ID].nodes.filter(n => n.id === 'n1')).toHaveLength(1);
        });
    });

    describe('node_updated — credentialIds (the credential-set bug)', () => {
        beforeEach(() => {
            applyAgenticGraphEvent(WORKFLOW_ID, {
                type: 'node_added',
                node: {
                    id: 'slack_fetch',
                    type: 'automation-slack',
                    label: 'Fetch Slack',
                },
            } as any);
        });

        it('applies credentialIds when delivered at the top level (lifted shape)', () => {
            // This is the exact payload _build_node_update_data produces for
            // <set_credentials node="slack_fetch" id="cred-uuid-123" />:
            // credentialIds at the top level of the event, config cleaned.
            applyAgenticGraphEvent(WORKFLOW_ID, {
                type: 'node_updated',
                nodeId: 'slack_fetch',
                operation: 'get_channel_messages',
                nodeLabel: 'Fetch Slack',
                credentialIds: { slack_oauth: 'cred-uuid-123' },
                config: {},
            } as any);

            expect(nodeData('slack_fetch')?.credentialIds).toEqual({
                slack_oauth: 'cred-uuid-123',
            });
        });

        it('applies credentialIds when delivered nested inside config (flat-blob shape)', () => {
            // The MCP bridge shape — credentialIds inside config after the
            // backend _to_mcp_event fix flattens metadata into the blob.
            applyAgenticGraphEvent(WORKFLOW_ID, {
                type: 'node_updated',
                nodeId: 'slack_fetch',
                config: {
                    operation: 'get_channel_messages',
                    credentialIds: { slack_oauth: 'cred-uuid-123' },
                    channel: 'C0000000005',
                },
            } as any);

            expect(nodeData('slack_fetch')?.credentialIds).toEqual({
                slack_oauth: 'cred-uuid-123',
            });
            // Plain config fields still land in data.config
            expect(nodeData('slack_fetch')?.config).toMatchObject({
                channel: 'C0000000005',
            });
        });

        it('applies disabled and mockedOutput flags', () => {
            applyAgenticGraphEvent(WORKFLOW_ID, {
                type: 'node_updated',
                nodeId: 'slack_fetch',
                disabled: true,
                mockedOutput: { messages: ['fake'] },
                config: {},
            } as any);

            expect(nodeData('slack_fetch')?.disabled).toBe(true);
            expect(nodeData('slack_fetch')?.mockedOutput).toEqual({
                messages: ['fake'],
            });
        });

        it('applies real config fields (channel) without dropping them', () => {
            applyAgenticGraphEvent(WORKFLOW_ID, {
                type: 'node_updated',
                nodeId: 'slack_fetch',
                config: { channel: 'C0000000005' },
            } as any);

            expect(nodeData('slack_fetch')?.config).toMatchObject({
                channel: 'C0000000005',
            });
        });

        it('skip-pass: pure animation-state re-assert does not allocate or wipe credentials', () => {
            // Set credentials first
            applyAgenticGraphEvent(WORKFLOW_ID, {
                type: 'node_updated',
                nodeId: 'slack_fetch',
                credentialIds: { slack_oauth: 'cred-uuid-123' },
                config: {},
            } as any);
            const arrBefore = graphRecords[WORKFLOW_ID].nodes;

            // Re-assert with empty payload — should no-op
            applyAgenticGraphEvent(WORKFLOW_ID, {
                type: 'node_updated',
                nodeId: 'slack_fetch',
                config: {},
            } as any);

            // Same array reference (no allocation) and creds preserved
            expect(graphRecords[WORKFLOW_ID].nodes).toBe(arrBefore);
            expect(nodeData('slack_fetch')?.credentialIds).toEqual({
                slack_oauth: 'cred-uuid-123',
            });
        });

        it('no-op when target node does not exist (avoids creating ghosts)', () => {
            applyAgenticGraphEvent(WORKFLOW_ID, {
                type: 'node_updated',
                nodeId: 'does_not_exist',
                credentialIds: { slack_oauth: 'cred-uuid-123' },
                config: {},
            } as any);

            expect(getNode('does_not_exist')).toBeUndefined();
        });
    });

    describe('edge_added (nested shape)', () => {
        it('creates an edge from event.edge with sourceId/targetId', () => {
            applyAgenticGraphEvent(WORKFLOW_ID, {
                type: 'edge_added',
                edge: { id: 'e1', sourceId: 'a', targetId: 'b' },
            } as any);

            const edges = graphRecords[WORKFLOW_ID].edges;
            expect(edges).toHaveLength(1);
            expect(edges[0]).toMatchObject({ id: 'e1', source: 'a', target: 'b' });
        });

        it('accepts source/target alias (MCP-bridge normalized shape)', () => {
            applyAgenticGraphEvent(WORKFLOW_ID, {
                type: 'edge_added',
                edge: { id: 'e2', source: 'a', target: 'b' },
            } as any);
            expect(graphRecords[WORKFLOW_ID].edges[0]).toMatchObject({
                id: 'e2',
                source: 'a',
                target: 'b',
            });
        });

        it('forwards sourceHandle for multi-output nodes', () => {
            applyAgenticGraphEvent(WORKFLOW_ID, {
                type: 'edge_added',
                edge: {
                    id: 'e3', sourceId: 'iter', targetId: 'body',
                    sourceHandle: 'loop',
                },
            } as any);
            expect(graphRecords[WORKFLOW_ID].edges[0]).toMatchObject({
                sourceHandle: 'loop',
            });
        });
    });

    describe('node_removed / edge_removed', () => {
        it('removes a node and its incident edges', () => {
            applyAgenticGraphEvent(WORKFLOW_ID, {
                type: 'node_added',
                node: { id: 'a', type: 'agent', label: 'A' },
            } as any);
            applyAgenticGraphEvent(WORKFLOW_ID, {
                type: 'node_added',
                node: { id: 'b', type: 'agent', label: 'B' },
            } as any);
            applyAgenticGraphEvent(WORKFLOW_ID, {
                type: 'edge_added',
                edge: { id: 'e1', sourceId: 'a', targetId: 'b' },
            } as any);

            applyAgenticGraphEvent(WORKFLOW_ID, {
                type: 'node_removed',
                nodeId: 'a',
            } as any);

            expect(getNode('a')).toBeUndefined();
            expect(graphRecords[WORKFLOW_ID].edges).toHaveLength(0);
        });

        it('removes a single edge by id', () => {
            applyAgenticGraphEvent(WORKFLOW_ID, {
                type: 'node_added',
                node: { id: 'a', type: 'agent', label: 'A' },
            } as any);
            applyAgenticGraphEvent(WORKFLOW_ID, {
                type: 'node_added',
                node: { id: 'b', type: 'agent', label: 'B' },
            } as any);
            applyAgenticGraphEvent(WORKFLOW_ID, {
                type: 'edge_added',
                edge: { id: 'e1', sourceId: 'a', targetId: 'b' },
            } as any);

            applyAgenticGraphEvent(WORKFLOW_ID, {
                type: 'edge_removed',
                edgeId: 'e1',
            } as any);

            expect(graphRecords[WORKFLOW_ID].edges).toHaveLength(0);
        });
    });

    describe('node_processing_start', () => {
        it('flips an existing node to the editing animation state', () => {
            applyAgenticGraphEvent(WORKFLOW_ID, {
                type: 'node_added',
                node: { id: 'n1', type: 'agent', label: 'N1' },
            } as any);

            applyAgenticGraphEvent(WORKFLOW_ID, {
                type: 'node_processing_start',
                nodeId: 'n1',
            } as any);

            expect(nodeData('n1')?.mcpAnimationState).toBe('editing');
        });
    });
});
