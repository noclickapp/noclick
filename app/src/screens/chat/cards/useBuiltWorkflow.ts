// The automation a build through the platform API draws on its card: its graph read on /v1 with the page's client
// (Workflow.graph(): each step with its place and settings, never a secret, and the connections between them), read
// again every few seconds while `follow` is on, as the builder adds to it.
import { useEffect, useState } from 'react';
import { useClient } from '@/sdk/client';
import { Workflow, type WorkflowGraph as ApiGraph } from 'noclick';
import type { SavedGraph } from '@/lib/graphPreview';

/** An automation as a card draws it: its name, and its steps and connections as the workflow stores them. */
export interface WorkflowGraph {
    name: string;
    blob: SavedGraph;
}

const FOLLOW_MS = 4000;

/** The graph as the card draws it: its name, and its steps and connections as the workflow stores them. */
export function builtWorkflowOf(graph: ApiGraph): WorkflowGraph {
    const { nodes, edges } = graph.raw;
    return {
        name: graph.name || 'Untitled',
        blob: {
            nodes: Array.isArray(nodes) ? (nodes as SavedGraph['nodes']) : [],
            edges: Array.isArray(edges) ? (edges as SavedGraph['edges']) : [],
        },
    };
}

export function useBuiltWorkflow(workflowId: string | undefined, follow: boolean): { graph: WorkflowGraph | null; error: string | null } {
    const client = useClient();
    const [graph, setGraph] = useState<WorkflowGraph | null>(null);
    const [error, setError] = useState<string | null>(null);
    useEffect(() => {
        if (!workflowId) return;
        let cancelled = false;
        const workflow = Workflow.fromId(workflowId, { client });
        const read = async () => {
            try {
                const drawn = builtWorkflowOf(await workflow.graph());
                if (cancelled) return;
                setGraph(drawn);
                setError(null);
            } catch (e) {
                if (!cancelled) setError(e instanceof Error ? e.message : 'Could not read the workflow');
            }
        };
        void read();
        const timer = follow ? window.setInterval(() => void read(), FOLLOW_MS) : undefined;
        return () => {
            cancelled = true;
            window.clearInterval(timer);
        };
    }, [client, workflowId, follow]);
    return { graph, error };
}
