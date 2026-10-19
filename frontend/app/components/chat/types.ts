import type { ContentItem } from '~/types/socket-schema.generated';

export type { ContentItem } from '~/types/socket-schema.generated';

// Frontend-specific AgenticStep interface that extends backend type with UI state
export interface AgenticStep {
    id: string;
    text: string;
    status: 'pending' | 'in_progress' | 'completed';
    subSteps?: AgenticStep[];
    isExpanded?: boolean;  // UI state for expansion
}

// Workflow edit event types for visual display in chat
export type WorkflowEditEventType =
    | 'started'
    | 'node_added'
    | 'node_removed'
    | 'node_updated'
    | 'node_processing'
    | 'node_config_filling'
    | 'edge_added'
    | 'edge_removed'
    | 'text_chunk'
    | 'status'
    | 'open_workflow'
    | 'complete'
    | 'error'
    // One op the builder ran and what it acted on (lib/builderSteps).
    | 'builder_step';

export interface WorkflowEditEvent {
    id: string;
    type: WorkflowEditEventType;
    nodeType?: string;       // e.g., 'automation-google-sheets'
    nodeLabel?: string;      // e.g., 'Google Sheets'
    nodeId?: string;
    prompt?: string;         // For 'started' event
    error?: string;          // For 'error' event
    timestamp: number;
    status: 'pending' | 'in_progress' | 'completed';
    // Expanded view data (for showing progress like WorkflowGenerationView)
    operation?: string;      // Selected operation name
    config?: Record<string, any>;  // Config fields being filled
    // Edge event data
    edgeId?: string;
    sourceNodeId?: string;
    sourceNodeLabel?: string;
    sourceNodeType?: string;
    targetNodeId?: string;
    targetNodeLabel?: string;
    targetNodeType?: string;
    // builder_step: the op, what it acted on, the app of a step it only knows by type, the field it set, an edge's
    // ends; its batch and place in it, and how it went (running, then ok or failed with why)
    op?: string;
    target?: string;
    node_type?: string;
    field?: string;
    ends?: { label?: string; node_type?: string }[];
    batch?: number;
    index?: number;
    state?: 'running' | 'ok' | 'failed';
    reason?: string;
}

// Inline edit segment for interleaving text and events in order
export type EditSegment =
    | { type: 'text'; text: string }
    | { type: 'events'; events: WorkflowEditEvent[] };

// Frontend message interface for chat messages
export interface Message {
    text: string;
    isUser: boolean;
    status?: string;
    component?: boolean | string;
    props?: Record<string, unknown>;
    importMap?: Record<string, unknown>;
    isComplete?: boolean;
    agenticSteps?: AgenticStep[];
    workflowEditEvents?: WorkflowEditEvent[];  // Visual workflow edit updates
    editSegments?: EditSegment[];               // Inline interleaved text + events (agentic edits)
    editStatus?: string;                         // Current operation status shown during "thinking" (e.g. "Searching workflows...")
    editSteps?: string[];                        // Accumulated tool call/thinking steps (shown as expandable log)
    content?: ContentItem[];
    // When set on a user message, the bubble renders as an n8n-import badge
    // (logo + node count) instead of plain text — used to show the user
    // that their pasted n8n workflow is being translated.
    n8nImportNodeCount?: number;
    // Generation ID for the builder run that produced this assistant message.
    // Persisted via useCachedValtioState so a page refresh can hydrate from
    // the backend snapshot for that gen — same path as a relay reconnect.
    // Set on `started`; absent on user messages and on legacy persisted
    // messages from before this field existed.
    generationId?: string;
    // True for assistant messages whose run was cancelled by the user: the
    // panel says it was stopped there and shows no live activity.
    wasInterrupted?: boolean;
    // Set for assistant messages whose run ended with outcome='failed' (e.g. a
    // mid-stream LLM error): the panel says so with a Try again instead of
    // vanishing or showing a success summary.
    failed?: boolean;
    error?: string;
    // Set for assistant messages whose run stopped without the builder saying it
    // had finished (outcome='incomplete', and the persisted row's `incomplete`):
    // no error happened, and the panel says it stopped with a Try again.
    incomplete?: boolean;
    /** Machine-readable failure class from the terminal frame (e.g. provider_key_missing). */
    errorCode?: string;
    errorMeta?: Record<string, string>;
    // Set on the trailing assistant of a conversation paused on <ask/>. The
    // BuilderInputBridge reads this on restore and shows the ask drawer
    // without needing a separate hydrate step.
    pendingAsk?: {
        ask_id: string;
        title?: string | null;
        inputs: Array<Record<string, unknown>>;
    } | null;
}
