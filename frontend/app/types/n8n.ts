/**
 * TypeScript types for n8n workflow JSON format.
 *
 * These types describe the subset accepted by the workflow import parser
 * and allow type-safe parsing of n8n workflow JSON on the frontend.
 */

export interface N8nNode {
    id?: string;
    name: string;
    type: string;
    position: [number, number]; // [x, y] coordinates
    parameters?: Record<string, any>;
    typeVersion: number | string;

    // Optional fields
    webhookId?: string;
    notes?: string;
    notesInFlow?: boolean;
    credentials?: Record<string, { id?: string; name?: string }>;
    disabled?: boolean;

    // Sticky note specific
    color?: number;
    width?: number;
    height?: number;
    content?: string;
}

export interface ConnectionTarget {
    node: string; // Target node name
    type: string; // Connection type (main, ai_languageModel, ai_tool, etc.)
    index: number; // Connection index
}

export interface N8nWorkflow {
    id?: string;
    name?: string;
    nodes: N8nNode[];
    connections: Record<string, Record<string, ConnectionTarget[][]>>;

    // Optional fields
    meta?: {
        instanceId: string;
        templateCredsSetupCompleted?: boolean;
    };
    tags?: Array<string | { id: string; name: string }>;
    active?: boolean;
    description?: string;
    notes?: string;
    settings?: Record<string, any>;
    versionId?: string;
    pinData?: Record<string, any>;
    staticData?: Record<string, any>;
}

export function isN8nWorkflow(data: any): data is N8nWorkflow {
    return (
        typeof data === 'object' &&
        data !== null &&
        Array.isArray(data.nodes) &&
        typeof data.connections === 'object'
    );
}

// n8n node type constants
export const N8N_NODE_TYPES = {
    STICKY_NOTE: 'n8n-nodes-base.stickyNote',
} as const;

/**
 * Determines if an n8n node is a sticky note.
 */
export function isStickyNote(node: N8nNode): boolean {
    return node.type === N8N_NODE_TYPES.STICKY_NOTE;
}

/**
 * Determines the ReactFlow node type based on n8n node type.
 */
export function getReactFlowNodeType(n8nNode: N8nNode): string {
    // Sticky notes should be rendered with dedicated sticky note component
    if (isStickyNote(n8nNode)) {
        return 'stickyNote';
    }

    // Everything else maps to ReactFlow's built-in 'default' node. (The legacy
    // 'pythonNode' generic renderer was removed; the real n8n paste flow routes
    // through backend AI translation into typed NoClick nodes — see FlowCanvas
    // onN8nWorkflowPaste — and doesn't go through this converter.)
    return 'default';
}
