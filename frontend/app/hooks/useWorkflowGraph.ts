// One workflow's saved graph and name, read with workflow:get, and read again every few seconds while `follow` is
// on (how a card in the chat draws an agent while the builder is still adding to it) or when `reload` asks.
import { useCallback, useEffect, useState } from 'react';
import type { ScaffoldBlob } from '~/lib/agentScaffold';
import { sendEventAsync } from '~/lib/socket-sender';
import { WorkflowGetRequest } from '~/types/socket-events.generated';

const FOLLOW_MS = 4000;

export interface WorkflowGraph {
    name: string;
    blob: ScaffoldBlob;
}

export function useWorkflowGraph(
    workflowId: string | undefined,
    follow: boolean
): { graph: WorkflowGraph | null; error: string | null; reload: () => void } {
    const [graph, setGraph] = useState<WorkflowGraph | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [version, setVersion] = useState(0);
    const reload = useCallback(() => setVersion((v) => v + 1), []);
    useEffect(() => {
        if (!workflowId) return;
        let cancelled = false;
        const read = async () => {
            try {
                const reply = (await sendEventAsync(WorkflowGetRequest.create({ workflow_id: workflowId, request_id: crypto.randomUUID() }))) as {
                    workflow?: { name?: string; workflow_data?: { nodes?: unknown; edges?: unknown } };
                    error?: string;
                };
                if (cancelled) return;
                if (reply.error || !reply.workflow) throw new Error(reply.error || 'Workflow not found');
                const data = reply.workflow.workflow_data ?? {};
                setGraph({
                    name: reply.workflow.name || 'Untitled',
                    blob: {
                        nodes: Array.isArray(data.nodes) ? (data.nodes as ScaffoldBlob['nodes']) : [],
                        edges: Array.isArray(data.edges) ? (data.edges as ScaffoldBlob['edges']) : [],
                    },
                });
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
    }, [workflowId, follow, version]);
    return { graph, error, reload };
}
