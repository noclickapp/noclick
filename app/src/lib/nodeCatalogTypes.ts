// The node catalog's shapes as a page receives them: serialized on the host's
// server, so a page reads them without the components and schemas behind them.

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
    /** The category the node's definition declares (NodeDefinition.category); absent when none. */
    category?: string;
    /** Search aliases the node's definition declares (NodeDefinition.keywords); absent when none. */
    keywords?: string[];
    /** Default canvas placement size (used by the chat/MCP builders). */
    dimensions: SerializedNodeDimensions;
    /** Operation consts stamped `x-is-trigger` in the schema; absent when none.
     *  Lets light surfaces tell a trigger without the schemas. */
    triggerOps?: string[];
    /** Credential types (and legacy raw schema titles) that wear this node's mark: each is listed on the first node
     *  (in schema order) declaring it. Lets credential icons resolve without the schemas. */
    credentialKeys?: string[];
    /** The credential types this node accepts, its primary first (absent for a node that takes none). Lets the
     *  credential-service lists (Connections, the create dialog) render without the schemas. */
    acceptedCredentialTypes?: string[];
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
    `value` is the operation's own name (an agent_tool_operations entry). */
export interface ProviderToolOperation {
    value: string;
    name: string;
    description: string;
    category: string;
}

/** An integration that can be wired into an agent's tools handle, with the
    operations it exposes, for pickers of an agent's tools. All fields are
    serialized for the page. */
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
