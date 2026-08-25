// Derives the per-node progress list for BuilderProgress from the live/persisted
// graph events the chat already carries (gen.events → message.editSegments).
// Reuses WorkflowEditEventView's battle-tested consolidation (handles both the
// flat live shape and the nested persisted shape) and adds the two grounded
// extras the Ledger shows: the field currently being filled and a filled count
// (both from node_config_filling events — the only place that data exists).
import type { WorkflowEditEvent } from '../types';
import { normalizeEvents, consolidateEvents } from '../WorkflowEditEventView';

export interface BuilderProgressNode {
    nodeId: string;
    type?: string;
    label: string;
    operation?: string;
    /** queued (drafted, not started) · active (configuring) · done · removed */
    state: 'queued' | 'active' | 'done' | 'removed';
    /** Field currently being filled (node_config_filling.field), active nodes only. */
    currentField?: string;
    /** Count of distinct fields filled so far. */
    fieldsFilled: number;
}

export function deriveBuilderNodes(events: WorkflowEditEvent[]): BuilderProgressNode[] {
    if (!events || events.length === 0) return [];

    // Per-node field tracking from node_config_filling (the field name lives on
    // the event; consolidateEvents doesn't surface it).
    const fieldsByNode = new Map<string, { seen: Set<string>; last?: string }>();
    for (const e of normalizeEvents(events)) {
        const field = (e as { field?: string }).field;
        if (e.type === 'node_config_filling' && e.nodeId && field) {
            const entry = fieldsByNode.get(e.nodeId) ?? { seen: new Set<string>() };
            entry.seen.add(field);
            entry.last = field;
            fieldsByNode.set(e.nodeId, entry);
        }
    }

    return consolidateEvents(events).nodes.map((n) => {
        // Derive from the event TYPE (n.action), NOT n.status: composeMessages
        // force-stamps status:'completed' on every event, so status would mark
        // every node done immediately. action reflects the latest real event —
        // a node is done only once node_updated lands; 'processing' (operation
        // select / config fill) is the live, in-flight phase.
        const state: BuilderProgressNode['state'] =
            n.action === 'removed' ? 'removed' :
            n.action === 'updated' ? 'done' :
            n.action === 'processing' ? 'active' : 'queued';
        const fields = fieldsByNode.get(n.nodeId);
        return {
            nodeId: n.nodeId,
            type: n.nodeType,
            label: n.nodeLabel || 'Node',
            operation: n.operation,
            state,
            currentField: state === 'active' ? fields?.last : undefined,
            fieldsFilled: fields?.seen.size ?? 0,
        };
    });
}
