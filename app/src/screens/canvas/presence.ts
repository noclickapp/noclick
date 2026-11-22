// Who else has a workflow open on its canvas, and what each is doing, as the canvas's presence slot (`canvas.presence`
// in slots.ts) hands it over: their cursors and selections, the steps they move, add, change and remove before any of it
// is saved, and the builder edits they're making.
import type { Edge, Node } from '@xyflow/react';

/** A point on the canvas, in its own coordinates (not the screen's). */
export interface CollaboratorCursor {
    x: number;
    y: number;
}

/** Someone else with the workflow open. */
export interface Collaborator {
    id: string;
    name: string;
    email?: string;
    avatarUrl?: string;
    /** Their colour, for their cursor and the outline of what they've selected. */
    color: string;
    /** Null while their pointer is off the canvas. */
    cursor: CollaboratorCursor | null;
    selectedNodeIds: string[];
    /** False while they're idle or away. */
    isActive: boolean;
    lastActiveAt: number;
}

/** A change the builder is making to a step, for someone else's canvas to show while it lands. */
export interface AiEditInfo {
    status: 'processing' | 'complete';
    action: 'added' | 'removed' | 'updated';
    operation?: string;
    config?: Record<string, unknown>;
}

/** What the canvas tells presence, and what presence tells it back as others act. */
export interface PresenceOptions {
    workflowId: string;
    /** Each step with where it sits and its size (a cursor follows the centre of a step being dragged). */
    nodes?: Array<{ id: string; position: { x: number; y: number }; width?: number; height?: number }>;
    /** Off: no one else is followed (a skill's canvas). */
    enabled?: boolean;
    onNodeDrag?: (nodeId: string, position: { x: number; y: number }) => void;
    onNodeAdd?: (node: Node) => void;
    onNodeRemove?: (nodeId: string) => void;
    onNodeUpdate?: (nodeId: string, data: Record<string, unknown>) => void;
    onEdgeAdd?: (edge: Edge) => void;
    onEdgeRemove?: (edgeId: string) => void;
    /** Back after being offline: the canvas reads the workflow again, so it never saves over what others did meanwhile. */
    onReconnect?: () => void;
    onRemoteAiEditingStart?: (userId: string, nodeIds: string[]) => void;
    onRemoteAiEditingUpdate?: (userId: string, nodeId: string, info: AiEditInfo) => void;
    onRemoteAiEditingEnd?: (userId: string) => void;
}

/** Who else is here, and how the canvas tells them what this person does. */
export interface Presence {
    /** Everyone else (never this person). */
    collaborators: Collaborator[];
    /** A step's id to who else has it selected. */
    nodeSelections: Map<string, Collaborator[]>;
    updateLocalCursor: (cursor: CollaboratorCursor | null) => void;
    updateLocalSelection: (nodeIds: string[]) => void;
    broadcastNodeDrag: (nodeId: string, position: { x: number; y: number }) => void;
    broadcastNodeAdd: (node: Node) => void;
    broadcastNodeRemove: (nodeId: string) => void;
    broadcastNodeUpdate: (nodeId: string, data: Record<string, unknown>) => void;
    broadcastEdgeAdd: (edge: Edge) => void;
    broadcastEdgeRemove: (edgeId: string) => void;
    broadcastAiEditingStart: (nodeIds: string[]) => void;
    broadcastAiEditingUpdate: (nodeId: string, info: AiEditInfo) => void;
    broadcastAiEditingEnd: () => void;
}
