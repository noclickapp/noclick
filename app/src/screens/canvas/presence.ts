// Who else has a workflow open on its canvas, and what each is doing, as the canvas's presence slot (`canvas.presence`
// in slots.ts) hands it over: their cursors and selections, and the builder edits they're making. Their changes to the
// workflow reach the canvas once they're saved, as every writer's do, never before: a canvas only ever saves what its
// own person did.

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
    /** Back after being offline: the canvas reads the workflow again, so it never saves over what others did meanwhile. */
    onReconnect?: () => void;
    onRemoteAiEditingStart?: (userId: string, nodeIds: string[]) => void;
    onRemoteAiEditingUpdate?: (userId: string, nodeId: string, info: AiEditInfo) => void;
    onRemoteAiEditingEnd?: (userId: string) => void;
}

/** Who else is here, and how the canvas tells them where this person is. */
export interface Presence {
    /** Everyone else (never this person). */
    collaborators: Collaborator[];
    /** A step's id to who else has it selected. */
    nodeSelections: Map<string, Collaborator[]>;
    /** What this person may do with the workflow as presence last heard it (an access change made while the canvas is
     *  open reaches it here); null while presence knows nothing of it. */
    access: 'edit' | 'view' | null;
    updateLocalCursor: (cursor: CollaboratorCursor | null) => void;
    updateLocalSelection: (nodeIds: string[]) => void;
    broadcastAiEditingStart: (nodeIds: string[]) => void;
    broadcastAiEditingUpdate: (nodeId: string, info: AiEditInfo) => void;
    broadcastAiEditingEnd: () => void;
}
