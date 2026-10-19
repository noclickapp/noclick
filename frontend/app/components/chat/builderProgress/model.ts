// The parts of the canvas a builder turn touched, from the live/persisted graph events the chat already carries
// (gen.events → message.editSegments). Reuses WorkflowEditEventView's consolidation (it handles both the flat live
// shape and the nested persisted shape) and adds what the panel says about each part: whether the turn added,
// changed or removed it, the fields it filled, and the one it's filling now (node_config_filling events, the only
// place that data exists).
import type { WorkflowEditEvent } from '../types';
import { normalizeEvents, consolidateEvents } from '../WorkflowEditEventView';

export interface BuilderProgressNode {
    nodeId: string;
    type?: string;
    label: string;
    operation?: string;
    /** queued (drafted, not started) · active (configuring) · done · removed */
    state: 'queued' | 'active' | 'done' | 'removed';
    /** What the turn did to it: added it, changed one already there, or removed it. */
    change: 'added' | 'updated' | 'removed';
    /** Field currently being filled (node_config_filling.field), active nodes only. */
    currentField?: string;
    /** The fields it filled, in the order it filled them. */
    fields: string[];
}

export function deriveBuilderNodes(events: WorkflowEditEvent[]): BuilderProgressNode[] {
    if (!events || events.length === 0) return [];

    const fieldsByNode = new Map<string, string[]>();
    const added = new Set<string>();
    for (const e of normalizeEvents(events)) {
        if (e.type === 'node_added' && e.nodeId) added.add(e.nodeId);
        const field = (e as { field?: string }).field;
        if (e.type === 'node_config_filling' && e.nodeId && field) {
            const fields = fieldsByNode.get(e.nodeId) ?? [];
            if (!fields.includes(field)) fields.push(field);
            fieldsByNode.set(e.nodeId, fields);
        }
    }

    return consolidateEvents(events).nodes.map((n) => {
        // Derive from the event TYPE (n.action), NOT n.status: composeMessages force-stamps status:'completed' on
        // every event, so status would mark every node done immediately. A node is done only once node_updated
        // lands; 'processing' (operation select / config fill) is the live, in-flight phase.
        const state: BuilderProgressNode['state'] =
            n.action === 'removed' ? 'removed' : n.action === 'updated' ? 'done' : n.action === 'processing' ? 'active' : 'queued';
        const fields = fieldsByNode.get(n.nodeId) ?? [];
        return {
            nodeId: n.nodeId,
            type: n.nodeType,
            label: n.nodeLabel || 'Node',
            operation: n.operation,
            state,
            change: n.action === 'removed' ? 'removed' : added.has(n.nodeId) ? 'added' : 'updated',
            currentField: state === 'active' ? fields[fields.length - 1] : undefined,
            fields,
        };
    });
}
