// @vitest-environment jsdom
// Exercise the real Edit and Autofill requests with a hydrated canvas node.
// Credentials and other persisted metadata must reach the builder and replay.
import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createWorkflowNode } from '~/lib/applyNodeUpdate';
import { useCanvasWorkflowEdit } from '~/hooks/useCanvasWorkflowEdit';
import { sendEventAsync } from '~/lib/socket-sender';
import { workflowDebugStore } from '~/lib/workflow-debug-store';

vi.mock('~/lib/socket-receiver', () => ({ socketReceiver: { getSocket: () => ({}), on: () => vi.fn() } }));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn().mockResolvedValue({ success: true }) }));
vi.mock('~/lib/builderHydration', () => ({
    BUILDER_EDIT_TIMEOUT_MS: 1000,
    subscribeToBuilderResponse: () => vi.fn(),
}));

afterEach(() => vi.clearAllMocks());

describe('builder snapshots', () => {
    it.each(['edit', 'autofill'] as const)('%s preserves connected and disabled nodes', async (mode) => {
        const config = {
            operation: 'claude_code', message: 'Monitor incoming updates',
            credentialIds: { agent_claude_code_oauth: 'saved-credential' },
            disabled: true, userFields: ['message'], mockedOutput: { preview: true },
        };
        const node = createWorkflowNode('agent', 'agent', { x: 3, y: 4 }, config);
        const { result, unmount } = renderHook(() => useCanvasWorkflowEdit({
            workflowId: 'workflow', currentNodes: [node], currentEdges: [],
            onNodesChange: vi.fn(), onEdgesChange: vi.fn(),
        }));
        const update = vi.spyOn(workflowDebugStore, 'update');
        await act(async () => {
            if (mode === 'edit') await result.current.startEdit('Change the threshold');
            else await result.current.startAutofill('agent', 'fields');
        });
        const request = vi.mocked(sendEventAsync).mock.calls.at(-1)?.[0] as unknown as {
            current_graph: { nodes: Array<{ config: Record<string, unknown> }> };
        };
        expect(request.current_graph.nodes[0].config).toMatchObject(config);
        const recording = update.mock.calls.find(([value]) => value.recordedEvents?.length)?.[0].recordedEvents;
        expect(recording?.[0].eventData.nodes[0].config).toMatchObject(config);
        unmount();
        update.mockRestore();
    });
});
