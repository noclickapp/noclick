// Load one past execution into the shape RunResultsDialog renders — the graph
// snapshot, per-node status, node outputs and the agent's tool calls. Lifted out
// of FlowCanvas so the Dashboard tab can open the same Story popup for a run it
// lists, instead of growing a second run viewer. Hosted-only additions to the
// popup (the agent-inputs rail) ride the story-enricher seam below: this module
// ships to the open edition and must not import hosted modules.
import { sendEventAsync } from '~/lib/socket-sender';
import { getNodeIconMeta } from '~/lib/nodeIconRegistry';
import { toReplayToolCalls, type ReplayToolCall } from '~/components/workflow/ReplayToolCallsPanel';
import type { NodeRunResult } from '~/components/workflow/RunResultsDialog';

type Wire = Record<string, unknown>;

/** The stored snapshot rows `workflow:get_execution_detail` returns. Both
 *  stored shapes are readable: canvas nodes carry `data.label`, headless
 *  saves carry `config.label`. Typed so a node is also a `GraphNodeLite`. */
export interface SnapshotNode {
    id: string;
    type?: string;
    data?: { label?: string; operation?: string; config?: Wire; [key: string]: unknown };
    config?: { label?: string; operation?: string; [key: string]: unknown };
}
interface NodeResultRow {
    node_id: string;
    last_run_status?: string;
    has_output?: boolean;
    last_run_error?: string | null;
    last_run_error_action?: NodeRunResult['errorAction'] | null;
}
interface ExecutionDetail {
    graph?: { nodes?: SnapshotNode[] };
    tool_calls?: ReplayToolCall[];
    node_results?: NodeResultRow[];
}

/** One request/response event by name (these have no generated request model). */
async function request<T>(event: string, payload: Wire): Promise<T | null> {
    return (await sendEventAsync({ event_name: event, ...payload } as unknown as Parameters<typeof sendEventAsync>[0])) as T | null;
}

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** True for a persisted execution id (optimistic "running" rows carry `run-<ts>`). */
export function isPersistedExecutionId(id: string): boolean {
    return UUID_RE.test(id);
}

/** Node results for a past run, agents first. Empty when nothing ran. */
export async function loadRunResults(workflowId: string, executionId: string): Promise<NodeRunResult[]> {
    return (await loadRunSnapshot(workflowId, executionId)).results;
}

export interface RunSnapshot {
    results: NodeRunResult[];
    /** The graph as stored with the run (ids + types), for icon/label lookups. */
    nodes: SnapshotNode[];
}

/** Extra RunResultsDialog props a hosted enricher contributes (the open edition
 *  contributes none). Spread onto the dialog by hosts that open a run outside
 *  the canvas. */
export type RunStoryExtras = Record<string, unknown>;

export interface RunStory extends RunSnapshot {
    extras: RunStoryExtras;
}

type RunStoryEnricher = (workflowId: string, snapshot: RunSnapshot) => Promise<RunStoryExtras>;
const enrichers: RunStoryEnricher[] = [];

/** Hosted bootstrap registers what the hosted popup shows beyond the snapshot
 *  (mirrors backend/cloud/bootstrap.py: the engine owns the seam and a working
 *  default, cloud registers implementations). */
export function registerRunStoryEnricher(enricher: RunStoryEnricher): void {
    enrichers.push(enricher);
}

/** Everything the Story popup needs for one past run, off the stored snapshot. */
export async function loadRunStory(workflowId: string, executionId: string): Promise<RunStory> {
    const snapshot = await loadRunSnapshot(workflowId, executionId);
    const extras = Object.assign({}, ...(await Promise.all(enrichers.map((e) => e(workflowId, snapshot))))) as RunStoryExtras;
    return { ...snapshot, extras };
}

export async function loadRunSnapshot(workflowId: string, executionId: string): Promise<RunSnapshot> {
    const [detail, outputsResp] = await Promise.all([
        request<ExecutionDetail>('workflow:get_execution_detail', { workflow_id: workflowId, execution_id: executionId }),
        request<{ outputs?: Record<string, unknown> }>('workflow:get_node_outputs', { workflow_id: workflowId, execution_id: executionId }),
    ]);
    const nodeById = new Map<string, SnapshotNode>((detail?.graph?.nodes || []).map((n) => [n.id, n]));
    const outputs: Record<string, unknown> = outputsResp?.outputs || {};
    const toolCallsByAgent: Record<string, ReplayToolCall[]> = {};
    for (const tc of detail?.tool_calls || []) {
        const aid = tc.agent_node_id;
        if (aid) (toolCallsByAgent[aid] ??= []).push(tc);
    }
    const results: NodeRunResult[] = (detail?.node_results || [])
        .filter((r) => ['completed', 'error', 'skipped'].includes(r.last_run_status ?? '') || r.has_output)
        .map((r) => {
            const gn = nodeById.get(r.node_id);
            const type = gn?.type || '';
            const meta = getNodeIconMeta(type);
            const isAgent = type === 'agent';
            const status: NodeRunResult['status'] =
                r.last_run_status === 'error' ? 'error' : r.last_run_status === 'skipped' ? 'skipped' : 'completed';
            const out = outputs[r.node_id];
            const pkgCalls = isAgent ? toReplayToolCalls(out) : [];
            return {
                nodeId: r.node_id,
                nodeType: type,
                label:
                    (gn?.data?.label as string | undefined) ||
                    (gn?.config?.label as string | undefined) ||
                    meta?.label ||
                    type ||
                    r.node_id,
                // The snapshot's node shape varies by how the run started:
                // FE-initiated runs store ReactFlow nodes (data.operation), headless
                // webhook/cron/agent runs store the backend blob (config.operation) —
                // and headless runs are exactly the trigger-fired ones, so missing
                // this read dropped the fired trigger into "Also ran".
                operation:
                    (gn?.data?.operation as string | undefined) ??
                    (gn?.config?.operation as string | undefined) ??
                    (gn?.data?.config?.operation as string | undefined),
                iconHtml: meta?.iconHtml,
                iconColor: meta?.iconColor,
                status,
                output: out,
                error: r.last_run_error || undefined,
                // Re-derived server-side from the stored message, so browsing a
                // past run offers the same fix the live one did.
                errorAction: r.last_run_error_action || undefined,
                isAgent,
                toolCalls: isAgent ? (pkgCalls.length > 0 ? pkgCalls : toolCallsByAgent[r.node_id] || []) : [],
            };
        });
    results.sort((a, b) => Number(b.isAgent) - Number(a.isAgent)); // agents first
    return { results, nodes: [...nodeById.values()] };
}
