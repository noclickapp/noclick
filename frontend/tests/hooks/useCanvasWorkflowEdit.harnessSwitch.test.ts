// @vitest-environment jsdom
// The builder moved an agent from OpenCode to Claude Code: its node_updated
// names the new label and sends what it removed as null. An open canvas must
// land both, or it keeps showing "OpenCode" over a claude-code chip and its
// next save writes the old harness's leftovers back.
import type { Node } from '@xyflow/react';
import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createWorkflowNode } from '~/lib/applyNodeUpdate';
import { useCanvasWorkflowEdit } from '~/hooks/useCanvasWorkflowEdit';
import { subscribeToBuilderResponse } from '~/lib/builderHydration';

vi.mock('~/lib/socket-receiver', () => ({ socketReceiver: { getSocket: () => ({}), on: () => vi.fn() } }));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn().mockResolvedValue({ success: true }) }));
vi.mock('~/lib/liveGraphStore', () => ({ recordRemoteDeletedNodes: vi.fn(), recordRemoteDeletedEdges: vi.fn() }));
vi.mock('~/lib/builderHydration', () => ({
    BUILDER_EDIT_TIMEOUT_MS: 1000,
    subscribeToBuilderResponse: vi.fn(() => vi.fn()),
}));

afterEach(() => vi.clearAllMocks());

describe('builder node_updated on an open canvas', () => {
    it('lands the new label and drops what the builder removed', async () => {
        const node = createWorkflowNode('agent-1', 'agent', { x: 0, y: 0 }, {
            label: 'OpenCode', model: 'opencode', opencode_model: 'opencode/big-pickle',
            message: 'Sync the boards',
            credentialIds: { agent_opencode: 'cred-opencode', agent_env: 'cred-env' },
        });
        let nodes: Node[] = [node];
        const onNodesChange = vi.fn((change: Node[] | ((prev: Node[]) => Node[])) => {
            nodes = typeof change === 'function' ? change(nodes) : change;
        });
        const { result, unmount } = renderHook(() => useCanvasWorkflowEdit({
            workflowId: 'workflow', currentNodes: nodes, currentEdges: [],
            onNodesChange, onEdgesChange: vi.fn(),
        }));
        await act(async () => {
            await result.current.startEdit('Switch the agent to Claude Code');
        });
        const { onEvent } = vi.mocked(subscribeToBuilderResponse).mock.calls.at(-1)![1] as {
            onEvent: (event: Record<string, unknown>) => void;
        };

        act(() => onEvent({
            event_type: 'node_updated', nodeId: 'agent-1', nodeType: 'agent', nodeLabel: 'Claude Code',
            operation: 'default', label: 'Claude Code',
            credentialIds: { agent_env: 'cred-env' },
            config: { model: 'claude-code', message: 'Sync the boards', opencode_model: null },
        }));

        const data = nodes[0].data as Record<string, unknown>;
        expect(data.label).toBe('Claude Code');
        expect(data.config).toEqual({ model: 'claude-code', message: 'Sync the boards' });
        expect(data.credentialIds).toEqual({ agent_env: 'cred-env' });
        unmount();
    });
});
