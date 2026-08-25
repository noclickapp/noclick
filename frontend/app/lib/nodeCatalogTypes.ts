// Shared, client-safe types for the public node catalog. Kept separate from
// nodeCatalog.server.ts (which imports the heavy registry) so route components can
// reference these shapes without any server-only or registry dependency.

export interface SerializedNodeDimensions {
    width: number;
    height: number;
    iconSize: number;
}

export interface SerializedNodeMeta {
    type: string;
    label: string;
    description: string;
    /** Tailwind `text-*` class, a raw hex/rgb value, or '' for multicolor marks. */
    iconColor: string;
    /** Pre-rendered brand-icon markup (an <img> or <svg> string); '' if no icon. */
    iconHtml: string;
    /** Default canvas placement size (used by the chat/MCP builders). */
    dimensions: SerializedNodeDimensions;
    /** Operation consts stamped `x-is-trigger` in the schema; absent when none.
     *  Lets light surfaces answer isTriggerSource without the schema bundle. */
    triggerOps?: string[];
}

export interface FieldInfo {
    key: string;
    title: string;
    description: string;
    type: string;
    required: boolean;
}

export interface OperationInfo {
    name: string;
    description: string;
    value: string;
    index: number;
    fields: FieldInfo[];
    /** Operation grouping from the schema's `x-category`. Defaults to 'General'. */
    category: string;
}

/** A single non-trigger operation an op-tool provider exposes as an agent tool.
    `value` is the real backend operation const (the agent_tool_operations entry). */
export interface ProviderToolOperation {
    value: string;
    name: string;
    description: string;
    category: string;
}

/** An integration that can be wired into an agent's tools handle, with the
    operations it exposes. Used by the /agents hub picker, connect pages, and the
    scaffold builder. All fields are serialized/registry-free for the client. */
export interface ProviderIntegration {
    type: string;
    slug: string;
    label: string;
    description: string;
    /** Tailwind `text-*` class, a raw hex/rgb value, or '' for multicolor marks. */
    iconColor: string;
    /** Pre-rendered brand-icon markup (an <img> or <svg> string); '' if none. */
    iconHtml: string;
    operations: ProviderToolOperation[];
}

/** A trigger that can be wired into an agent's input (left) handle to fire it.
    Built-in triggers (webhook/schedule/email/form) have operation null; integration
    triggers (Slack/Gmail/...) carry the default trigger operation to select. */
export interface TriggerOption {
    type: string;
    slug: string;
    label: string;
    description: string;
    iconColor: string;
    iconHtml: string;
    /** Trigger operation const for integration triggers; null for built-ins. */
    operation: string | null;
    /** Display name of the trigger operation (integration triggers). */
    operationLabel?: string;
    kind: 'builtin' | 'integration';
}
