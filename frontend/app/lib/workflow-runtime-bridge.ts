import type { Edge, Node } from '@xyflow/react';
import { normalizeNodeUpdatePayload, updateNodeInList } from './applyNodeUpdate';

type NodeSetter = (updater: (nodes: Node[]) => Node[]) => void;

interface WorkflowRuntimeState {
    readonly nodes: Node[];
    readonly edges: Edge[];
    setNodes: NodeSetter;
}

let runtimeState: WorkflowRuntimeState | null = null;

export const workflowRuntimeBridge = {
    register(state: WorkflowRuntimeState): void {
        runtimeState = state;
    },

    unregister(): void {
        runtimeState = null;
    },

    getNodes(): Node[] {
        return runtimeState?.nodes ?? [];
    },

    getEdges(): Edge[] {
        return runtimeState?.edges ?? [];
    },

    updateNodeData(nodeId: string, data: Record<string, unknown>): void {
        const state = runtimeState;
        if (!state) return;
        const update = normalizeNodeUpdatePayload(data as Record<string, any>);
        state.setNodes(nodes => updateNodeInList(nodes, nodeId, update));
    },
};
