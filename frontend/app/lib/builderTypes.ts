/**
 * The shapes the AI builder streams to the canvas.
 *
 * Types only. They were carried alongside a mock generator and its templates,
 * which the real builder replaced — keeping the two together meant every
 * consumer of a type pulled several hundred lines of stand-in workflows.
 */
// ============================================================================
// Types
// ============================================================================

/** Represents a node being generated in the workflow */
export interface GeneratedNode {
    id: string;
    type: string;
    label: string;
    description?: string;
    level: number;
    index: number;
    parentIds: string[];
    status: 'adding' | 'editing' | 'complete' | 'needs_input' | 'error';
    content: string;
    icon?: string;
    color?: string;
    // Node-drafting progress fields
    operation?: string;
    operationReason?: string;
    config?: Record<string, any>;
    userFields?: string[];
    error?: string;
    // Original position from template (preserved during fork/load)
    position?: { x: number; y: number };
    // Original dimensions from template (preserved for sticky notes)
    width?: number;
    height?: number;
}

/** Represents an edge connecting two nodes */
export interface GeneratedEdge {
    id: string;
    sourceId: string;
    targetId: string;
    sourceHandle?: string;  // For multi-output nodes (e.g., iteration: 'loop' or 'done')
    status: 'animating' | 'complete';
}

/** Represents a credential or input request from the AI */
export interface InputRequest {
    id: string;
    nodeId: string;
    type: 'credential' | 'selection' | 'text' | 'config' | 'env';
    label: string;
    description: string;
    options?: { id: string; label: string; icon?: string }[];
    /** Multi-select (type === 'selection'): render checkboxes and submit the
     *  chosen options comma-joined. From <ask multiple="true">. */
    multiple?: boolean;
    /** Sandbox env-var names the builder requested (type === 'env'). camelCase,
     *  as emitted by the backend ask parser. */
    envKeys?: { name: string; description?: string }[];
    /** Provider name (e.g., 'github', 'google', 'slack') used for OAuth flow */
    credentialType?: string;
    /** Specific credential types accepted (e.g., ['github_oauth', 'github_pat']) - if provided, used for filtering */
    acceptedCredentialTypes?: string[];
    required: boolean;
    /** Selected credential ID (set when user selects a credential) */
    value?: string;

    // Config field properties (for type: 'config')
    /** Node type for loading dynamic options (e.g., 'automation-google-sheets') */
    nodeType?: string;
    /** Field key in the node's config schema (e.g., 'spreadsheet_id', 'sheet_name') */
    fieldKey?: string;
    /** JSON Schema for the field (from node's schema) */
    fieldSchema?: Record<string, any>;
    /** Field this config depends on (e.g., 'sheet_name' depends on 'spreadsheet_id') */
    dependsOn?: string;
    /** Credential types required to load options for this field */
    requiredCredentialTypes?: string[];
    /** Snapshot of the node's credentialIds at ask emission — used by DynamicOptionsField to load options */
    credentialIds?: Record<string, string>;
    /** Snapshot of the node's current config (sibling fields) — used for depends_on resolution */
    nodeConfig?: Record<string, any>;
    /** Pre-fill the picker when drafting extracted a concrete value from the user's prompt. */
    defaultValue?: string;
}

/** Overall generation state */
export type GenerationPhase = 'idle' | 'generating' | 'awaiting_input' | 'complete';

/** Events emitted by the workflow generator */
export type GenerationEvent =
    | { type: 'node_start'; node: GeneratedNode }
    | { type: 'node_typing'; nodeId: string; content: string }
    | { type: 'node_complete'; nodeId: string }
    | { type: 'edge_add'; edge: GeneratedEdge }
    | { type: 'edge_complete'; edgeId: string }
    | { type: 'input_request'; request: InputRequest }
    | { type: 'generation_complete' };

// ============================================================================
// Workflow Templates
// ============================================================================

/** Structure for a workflow template */
