import type { LucideIcon } from 'lucide-react';
import type { Node } from '@xyflow/react';
import type { AgentTriggerSource, AgentWiredTool } from '~/utils/nodeSchemas';
import type { AgentChatAttachment } from '~/lib/agentChat';

/** Trigger/tool wiring of an agent node, projected for the agent-chat
 *  sidebar (computed canvas-side from nodes + edges). */
export interface AgentWiring {
    triggers: AgentTriggerSource[];
    tools: AgentWiredTool[];
}

export type BlockCategory = 'Input' | 'Display' | 'Interactive' | 'Agent';

export type FormFieldType =
    | 'text'
    | 'textarea'
    | 'number'
    | 'checkbox'
    | 'dropdown'
    | 'slider'
    | 'radio'
    | 'date'
    | 'color'
    | 'schedule'
    | 'list'
    | 'file'
    | 'credential';

export interface FormField {
    id: string;
    type: FormFieldType;
    label: string;
    placeholder?: string;
    required?: boolean;
    options?: (string | { label: string; value: string })[];
    min?: number;
    max?: number;
    step?: number;
    defaultValue?: string | number | boolean;
    /** Accept filter for `file` fields (e.g. "image/*", ".pdf"). Empty = any file. */
    accept?: string;
    /** Credential type to collect (e.g., 'google_sheets_oauth'). Only used when type is 'credential'. */
    credentialType?: string;
    /** Accepted credential types, derived from service registry based on credentialType. */
    acceptedCredentialTypes?: string[];
}

export interface BlockDefinition {
    type: string;
    label: string;
    category: BlockCategory;
    icon: LucideIcon;
    description: string;
    defaultW: number;
    defaultH: number;
    minW?: number;
    minH?: number;
    /** Corresponding workflow node type for auto-sync with the canvas */
    nodeType?: string;
    /** True when the block renders its content in an <iframe>. Iframes swallow
     *  wheel/pointer events, so on the canvas InterfaceNode shields them with a
     *  transparent overlay while the node is unselected. */
    usesIframe?: boolean;
}

export interface BlockConfig {
    label?: string;
    placeholder?: string;
    [key: string]: unknown;
}

export interface PlacedBlock {
    id: string;
    type: string;
    config: BlockConfig;
    output?: Record<string, unknown> | null;
    /** Top-level credentialIds from the underlying ReactFlow node (data.credentialIds).
     *  Used by the agent-chat block's Credentials panel; other blocks ignore it. */
    credentialIds?: Record<string, string>;
}

export interface BlockComponentProps {
    id: string;
    config: BlockConfig;
    isSelected: boolean;
    onConfigChange: (config: BlockConfig) => void;
    /** Execution output from the workflow node (available after a run) */
    output?: Record<string, unknown> | null;
    /** Called when a form block submits — triggers workflow execution with form values */
    onSubmit?: (values: Record<string, unknown>) => void;
    /** Read-only mode — disables interactive features like SDK bridge, form submit, uploads */
    isReadOnly?: boolean;
    /** Called when a user tries to interact in read-only mode (triggers fork prompt) */
    onInteraction?: () => void;
    /** Workflow context — used by agent-chat block to scope the conversation_id. */
    workflowId?: string;
    /** Called by the agent-chat block when the user sends a chat message. */
    onAgentChatSend?: (
        nodeId: string,
        message: string,
        model: string,
        /** The conversation to send into. Passed explicitly because the send may
         *  be minting it in the same call — reading it back from the node config
         *  would race the write and land the turn in the thread being left. */
        conversationKey?: string,
        /** Files attached to this message (already uploaded to R2). */
        attachments?: AgentChatAttachment[]
    ) => void;
    /** Current credential id mappings on the underlying node (data.credentialIds). */
    credentialIds?: Record<string, string>;
    /** Patch the underlying node's credentialIds — used by the agent-chat
     *  block's Credentials panel to wire up model-specific API keys. */
    onCredentialIdsChange?: (credentialIds: Record<string, string>) => void;
    /** Trigger/tool wiring of the underlying agent node — drives the agent-chat
     *  sidebar's Triggers and Tools sections. */
    agentWiring?: AgentWiring;
    /** Wire a new trigger or tool-provider node to the agent. Returns the
     *  new node id (the palette's tool flow continues into config). */
    onAgentWiringAdd?: (
        nodeType: string,
        role: 'trigger' | 'tool',
        operation?: string
    ) => string | void;
    /** Remove a wired trigger/tool (drops the edge; the node too when orphaned). */
    onAgentWiringRemove?: (edgeId: string, nodeId: string) => void;
    /** Patch a WIRED node's config (e.g. a provider's allowlist) — not this block's node. */
    onWiredNodeConfigPatch?: (
        nodeId: string,
        config: Record<string, unknown>
    ) => void;
    /** Patch a WIRED node's credentialIds. */
    onWiredNodeCredentialsChange?: (
        nodeId: string,
        credentialIds: Record<string, string>
    ) => void;
    /** Live accessor for a wired node's data (credentials + config) — the
     *  palette config step re-reads it every render. */
    getWiredNodeData?: (nodeId: string) => {
        nodeData: Record<string, unknown>;
        config: Record<string, unknown>;
        credentialIds: Record<string, string>;
    } | null;
    /** Optional host-side SDK bridge source for canvas/replay iframe blocks. */
    sdkBridge?: {
        getNodes: () => Node[];
        updateNodeData?: (
            nodeId: string,
            data: Record<string, unknown>
        ) => void;
        readOnly?: boolean;
    };
}
