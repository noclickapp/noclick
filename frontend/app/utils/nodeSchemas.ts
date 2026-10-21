/**
 * Node JSON schemas, the generated files under ~/schemas/nodes (backend/scripts/generate_socket_types.py),
 * loaded per node type: each file is its own lazy chunk, so a page fetches only the schemas of the node
 * types it shows. Every helper here reads synchronously over what has loaded, so a reader sits behind a
 * load: useNodeSchemas in a component, `await loadNodeSchemas(types)` elsewhere, and loadAllNodeSchemas
 * for the few that walk every type (search, the agent wiring palette). The server registers every file up
 * front (lib/nodeSchemas.server).
 */

// From the leaf, NOT credentialTypes: that module imports getNodeCredentialInfo
// from this one, and the resulting cycle made module-evaluation order load-bearing
// — any new import edge into the pair could 500 Vite SSR.
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { createLazyTypeStore, type LazyTypeStore } from '~/lib/lazyTypeStore';
// Type predicates + legacy-alias resolution live in the schema-free leaf
// utils/nodeMeta (backed by the slim generated nodeMeta.json), which also lists
// every type with a schema. Re-exported here so existing consumers keep a single import site.
import {
    LEGACY_NODE_TYPE_ALIASES,
    NODE_SCHEMA_TYPES,
    resolveNodeType,
    isAgentToolProviderType,
    isTriggerSource,
} from '~/utils/nodeMeta';

export { LEGACY_NODE_TYPE_ALIASES, NODE_SCHEMA_TYPES, resolveNodeType, isAgentToolProviderType, isTriggerSource };

type Schema = Record<string, any>;

// One lazy chunk per file. A file is named after its registry type minus `automation-`.
const SCHEMA_FILES = import.meta.glob<Schema>('../schemas/nodes/*.json', { import: 'default' });
const fileStem = (path: string) => path.slice(path.lastIndexOf('/') + 1, -'.json'.length);
const TYPE_BY_STEM = new Map(NODE_SCHEMA_TYPES.map((type) => [type.replace(/^automation-/, ''), type]));
const LOADER_BY_TYPE = new Map<string, () => Promise<Schema>>();
for (const [path, load] of Object.entries(SCHEMA_FILES)) {
    const type = TYPE_BY_STEM.get(fileStem(path));
    if (type) LOADER_BY_TYPE.set(type, load);
}

/** The schemas, loaded per node type (useNodeSchemas reads it). */
export const nodeSchemaStore: LazyTypeStore<Schema> = createLazyTypeStore((type) => LOADER_BY_TYPE.get(type));

const _warnedUnloaded = new Set<string>();

/**
 * The schemas loaded so far, by node type. A type whose schema hasn't loaded reads undefined (in development
 * it also says so on the console: the reader needs a load in front of it). Legacy aliases resolve on property
 * READ only — Object.keys/values/entries stay clean (no legacy keys leak into listings or credential scans).
 */
export const NODE_SCHEMAS: Record<string, any> = new Proxy(nodeSchemaStore.values as Record<string, Schema>, {
    get(target, prop) {
        if (typeof prop !== 'string') return (target as Record<string | symbol, unknown>)[prop];
        const type = prop in target ? prop : resolveNodeType(prop);
        const schema = target[type];
        if (schema === undefined && import.meta.env.DEV && LOADER_BY_TYPE.has(type) && !_warnedUnloaded.has(type)) {
            _warnedUnloaded.add(type);
            console.error(`[nodeSchemas] ${type}'s schema was read before it loaded`);
        }
        return schema;
    },
});

/** Gets the schema for a node type (undefined until it has loaded). */
export function getNodeSchema(nodeType: string): any | undefined {
    return NODE_SCHEMAS[nodeType];
}

/** Whether every listed type's schema has loaded. A type with no schema has nothing to load. */
export function nodeSchemasLoaded(types: Iterable<string | null | undefined>): boolean {
    return nodeSchemaStore.loaded(types);
}

/** Loads the listed types' schemas (each once; a type with no schema is skipped). */
export function loadNodeSchemas(types: Iterable<string | null | undefined>): Promise<void> {
    return nodeSchemaStore.load(types);
}

/** Loads every schema: for the readers that walk every type. */
export function loadAllNodeSchemas(): Promise<void> {
    return nodeSchemaStore.load(NODE_SCHEMA_TYPES);
}

/** Registers schema files already in hand (the server's eager import), keyed by their path. */
export function registerNodeSchemaFiles(files: Record<string, Schema>): void {
    const byType: Record<string, Schema> = {};
    for (const [path, schema] of Object.entries(files)) {
        const type = TYPE_BY_STEM.get(fileStem(path));
        if (type) byType[type] = schema;
    }
    nodeSchemaStore.put(byType);
}

function requireAllLoaded(reader: string): void {
    if (!nodeSchemasLoaded(NODE_SCHEMA_TYPES)) {
        throw new Error(`${reader} walks every node schema: await loadAllNodeSchemas() first`);
    }
}

/**
 * Whether a node is currently WIRED as an agent tool provider — a qualifying
 * type whose top handle feeds an AI agent's bottom handle. Drives the
 * allowlist config UI and provider-mode validation. Mirrors the backend's
 * is_node_op_provider (nodes/agent/node_op_tools.py). Structural types so
 * callers can pass xyflow Node/Edge objects without importing them here.
 */
export function isWiredAsAgentToolProvider(
    nodeId: string,
    nodes: Array<{ id: string; type?: string }>,
    edges: Array<{ source: string; target: string; targetHandle?: string | null }>,
): boolean {
    return getToolProviderConsumerTypes(nodeId, nodes, edges).length > 0;
}

/**
 * The kinds of consumers this provider node feeds through its top→bottom
 * wiring: AI agents and/or hosting-mode MCP servers. Drives provider-mode
 * config UI and its consumer-aware copy. Empty = not provider-wired.
 */
export function getToolProviderConsumerTypes(
    nodeId: string,
    nodes: Array<{ id: string; type?: string }>,
    edges: Array<{ source: string; target: string; targetHandle?: string | null }>,
): Array<'agent' | 'mcp-server'> {
    const node = nodes.find(n => n.id === nodeId);
    if (!node || !isAgentToolProviderType(node.type)) return [];
    const typeById = new Map(nodes.map(n => [n.id, n.type]));
    const consumers = new Set<'agent' | 'mcp-server'>();
    for (const e of edges) {
        if (e.source !== nodeId || e.targetHandle !== 'bottom') continue;
        const t = typeById.get(e.target);
        if (t === 'agent' || t === 'mcp-server') consumers.add(t);
    }
    return [...consumers];
}

/**
 * An exposable (non-trigger) operation of an integration node, for the
 * agent-tool allowlist UI. Mirrors the backend's list_node_operations.
 */
/** A field on an operation that can be resource-scoped — has both
 *  `x-dynamic-options` (loader-backed picker) AND `x-resource-type`
 *  (identity tag). Backend enforcement at runtime (run_op._check_field_scopes
 *  and tool_execution._enforce_field_scopes) reads the matching
 *  `agent_tool_operations[i].field_scopes[field]` allowlist. */
export interface AgentToolScopableField {
    field: string;
    label: string;
    resourceType: string;
    /** Loader field_name (what the load_field_options socket call expects);
     *  usually matches `field` but can differ for back-compat schemas. */
    loaderField: string;
    /** Parent field this dependent loader needs context from (e.g. `sheet_name`
     *  depends on `spreadsheet_id`). The scope picker gates this field on the
     *  parent's scope: empty parent scope → can't enumerate options. */
    dependsOn?: string;
}

export interface AgentToolOperation {
    operation: string;
    displayName: string;
    category: string | null;
    description: string;
    /** Author-supplied search synonyms (joined `x-keywords`), so the allowlist
     *  picker's search matches intent words the label doesn't contain. */
    keywords: string;
    /** Operation has ID fields served by dynamic-option loaders — the agent
     *  gets an auto-included {provider}__lookup_options tool for these. */
    hasDynamicFields: boolean;
    /** Subset of fields scopable via field_scopes (x-dynamic-options +
     *  x-resource-type). Empty for ops that have ID fields but no
     *  resource-type tag (e.g. unannotated nodes). */
    scopableFields: AgentToolScopableField[];
}

/** An entry in `agent_tool_operations`: either a bare operation name string
 *  (unscoped, legacy/default shape) OR a scoped object pinning specific
 *  resource IDs to specific fields. Backend validator
 *  validate_agent_tool_operations enforces the schema. */
export type AgentToolOperationEntry =
    | string
    | { operation: string; field_scopes: Record<string, string[]> };

/** Pull the operation name from a mixed-shape entry. Used by callers that
 *  only care about which ops are selected (display, picker keyboard nav,
 *  edge-presence checks) — they don't need to know about field_scopes. */
export function operationName(entry: AgentToolOperationEntry): string {
    return typeof entry === 'string' ? entry : entry.operation;
}

/** Flatten mixed entries to a names-only array. Cheap; safe on null. */
export function operationNamesOf(
    entries: AgentToolOperationEntry[] | string[] | null | undefined,
): string[] {
    if (!Array.isArray(entries)) return [];
    return entries.map(e =>
        typeof e === 'string' ? e : (e?.operation ?? ''),
    ).filter(Boolean);
}

/** Field_scopes for a given operation, indexed by field name. Empty if the
 *  op is unscoped. */
export function fieldScopesFor(
    entries: AgentToolOperationEntry[] | null | undefined,
    operation: string,
): Record<string, string[]> {
    if (!Array.isArray(entries)) return {};
    for (const e of entries) {
        if (typeof e === 'object' && e?.operation === operation && e.field_scopes) {
            return e.field_scopes;
        }
    }
    return {};
}

/**
 * Enumerates the operations of a node that can be exposed as agent tools,
 * derived from the schema's per-operation union (triggers excluded).
 */
export function getAgentToolOperations(nodeType: string): AgentToolOperation[] {
    const schema = NODE_SCHEMAS[nodeType];
    if (!schema) return [];
    const config = schema.properties?.config ?? {};
    const defs = schema.$defs ?? {};
    // Union shape (oneOf/anyOf of $refs) or single-model shape (direct $ref) —
    // mirrors the backend's _iter_operation_defs so both sides enumerate the
    // same operations for every stamped schema.
    const refs: Array<{ $ref?: string }> =
        config.oneOf ?? config.anyOf ?? (config.$ref ? [{ $ref: config.$ref }] : []);

    const ops: AgentToolOperation[] = [];
    for (const ref of refs) {
        const key = ref.$ref?.split('/').pop();
        const member = key ? defs[key] : undefined;
        const op = member?.properties?.operation;
        const constValue = op?.const ?? op?.enum?.[0];
        if (!constValue || op?.['x-is-trigger']) continue;
        let hasDynamicFields = false;
        const scopableFields: AgentToolScopableField[] = [];
        for (const [field, propRaw] of Object.entries(member.properties ?? {})) {
            const prop = propRaw as Record<string, any> | null | undefined;
            if (field === 'operation' || !prop || prop['ui:hidden']) continue;
            const dyn = prop['x-dynamic-options'];
            if (!dyn) continue;
            hasDynamicFields = true;
            const resourceType = prop['x-resource-type'];
            if (typeof resourceType === 'string' && resourceType) {
                const dependsOn = typeof dyn === 'object' && typeof dyn?.depends_on === 'string'
                    ? dyn.depends_on
                    : undefined;
                scopableFields.push({
                    field,
                    label: prop.title || field,
                    resourceType,
                    loaderField: (typeof dyn === 'object' && dyn?.field_name) || field,
                    dependsOn,
                });
            }
        }
        ops.push({
            operation: constValue,
            displayName: op['x-display-name'] ?? op.title ?? constValue,
            category: op['x-category'] ?? null,
            description: member.description ?? '',
            keywords: Array.isArray(op['x-keywords'])
                ? op['x-keywords'].join(' ')
                : op['x-keywords'] ?? '',
            hasDynamicFields,
            scopableFields,
        });
    }
    return ops;
}

/** A trigger node wired directly into an agent's input — one chip under the
 *  agent's Message field. */
export interface AgentTriggerSource {
    edgeId: string;
    nodeId: string;
    nodeType: string;
    /** User-given node label; empty when unset (render the type's default). */
    label: string;
    /** Selected operation — set for integration triggers (x-is-trigger ops). */
    operation?: string;
}

/**
 * Trigger nodes wired directly into an agent's input handle. When one fires,
 * the agent runs with the fired event delivered as part of its user turn
 * (backend: AgentNode._resolve_trigger_event). Bottom-handle edges are
 * excluded — tool providers and alarms have their own visual surfaces.
 */
export function getAgentTriggerSources(
    agentNodeId: string,
    nodes: Array<{ id: string; type?: string; data?: Record<string, any> }>,
    edges: Array<{ id: string; source: string; target: string; targetHandle?: string | null }>,
): AgentTriggerSource[] {
    const byId = new Map(nodes.map(n => [n.id, n]));
    const sources: AgentTriggerSource[] = [];
    for (const e of edges) {
        if (e.target !== agentNodeId || e.targetHandle === 'bottom') continue;
        const src = byId.get(e.source);
        if (!src?.type) continue;
        const operation = (src.data?.operation ?? src.data?.config?.operation) as
            | string
            | undefined;
        if (!isTriggerSource(src.type, operation)) continue;
        sources.push({
            edgeId: e.id,
            nodeId: src.id,
            nodeType: src.type,
            label: (src.data?.label as string | undefined) || '',
            operation,
        });
    }
    return sources;
}

/**
 * Agent nodes with NO trigger wired into their input handle — i.e. chat-driven
 * agents that run by chatting rather than by a fired event. Used after an AI
 * build to surface such agents in the Interface tab. Reuses
 * getAgentTriggerSources so the "what counts as a trigger" rule stays in one place.
 */
export function getTriggerlessAgents<
    N extends { id: string; type?: string; data?: Record<string, any> },
>(
    nodes: N[],
    edges: Array<{ id: string; source: string; target: string; targetHandle?: string | null }>,
): N[] {
    return nodes.filter(
        (n) => n.type === 'agent' && getAgentTriggerSources(n.id, nodes, edges).length === 0,
    );
}

/** A trigger operation of an integration node (x-is-trigger), for pickers
 *  that wire integration triggers (e.g. the agent chat sidebar). */
export interface TriggerOperation {
    operation: string;
    displayName: string;
    description: string;
    /** Author-supplied search synonyms (joined `x-keywords`), so trigger search
     *  matches intent words the display name doesn't contain. */
    keywords: string;
}

/**
 * Enumerates a node type's TRIGGER operations (x-is-trigger) — the complement
 * of getAgentToolOperations' enumeration, same schema walk.
 */
export function getTriggerOperations(nodeType: string): TriggerOperation[] {
    const schema = NODE_SCHEMAS[nodeType];
    if (!schema) return [];
    const config = schema.properties?.config ?? {};
    const defs = schema.$defs ?? {};
    const refs: Array<{ $ref?: string }> =
        config.oneOf ?? config.anyOf ?? (config.$ref ? [{ $ref: config.$ref }] : []);
    const ops: TriggerOperation[] = [];
    for (const ref of refs) {
        const key = ref.$ref?.split('/').pop();
        const member = key ? defs[key] : undefined;
        const op = member?.properties?.operation;
        const constValue = op?.const ?? op?.enum?.[0];
        if (!constValue || !op?.['x-is-trigger']) continue;
        ops.push({
            operation: constValue,
            displayName: op['x-display-name'] ?? op.title ?? constValue,
            description: member.description ?? '',
            keywords: Array.isArray(op['x-keywords'])
                ? op['x-keywords'].join(' ')
                : op['x-keywords'] ?? '',
        });
    }
    return ops;
}

/** A tool-provider node wired to an agent's bottom handle — one row in the
 *  agent chat sidebar's Tools section. */
export interface AgentWiredTool {
    edgeId: string;
    nodeId: string;
    nodeType: string;
    /** User-given node label; empty when unset (render the type's default). */
    label: string;
    /** Allowlisted operations (config.agent_tool_operations). */
    operations: string[];
    /** Node has credential slots but none connected — tool calls will fail. */
    credentialsMissing: boolean;
    /** Attached credential ids (credential_type → id) — lets consumers check
     *  credential HEALTH (revoked/deleted) against the loaded list. */
    credentialIds: Record<string, string>;
}

/**
 * Tool-provider nodes wired to an agent's bottom handle, with their allowlist
 * state. Mirrors is_node_op_provider (backend) for display purposes.
 */
export function getAgentToolProviders(
    agentNodeId: string,
    nodes: Array<{ id: string; type?: string; data?: Record<string, any> }>,
    edges: Array<{ id: string; source: string; target: string; targetHandle?: string | null }>,
    hasUnconnectedCredentials: (nodeType: string, credentialIds: Record<string, string>, nodeData?: Record<string, any>) => boolean,
): AgentWiredTool[] {
    const byId = new Map(nodes.map(n => [n.id, n]));
    const tools: AgentWiredTool[] = [];
    for (const e of edges) {
        if (e.target !== agentNodeId || e.targetHandle !== 'bottom') continue;
        const src = byId.get(e.source);
        // The four STRUCTURAL_AGENT_TOOL_TYPES are wirable here without an
        // allowlist (their tool surfaces are emitted by the node itself).
        if (!src?.type || !(isAgentToolProviderType(src.type) || STRUCTURAL_AGENT_TOOL_TYPES.has(src.type))) continue;
        const cfg = (src.data?.config ?? {}) as Record<string, any>;
        const credentialIds = (src.data?.credentialIds ?? cfg.credentialIds ?? {}) as Record<string, string>;
        tools.push({
            edgeId: e.id,
            nodeId: src.id,
            nodeType: src.type,
            label: (src.data?.label as string | undefined) || '',
            // Always present as op names — mixed-shape entries (scoped objects)
            // are normalized for downstream display (sidebar count chip, etc).
            operations: operationNamesOf(cfg.agent_tool_operations),
            credentialsMissing: hasUnconnectedCredentials(src.type, credentialIds, src.data),
            credentialIds,
        });
    }
    return tools;
}

/**
 * Structural tool-provider node types: not integration-operation allowlists,
 * but their own first-class providers that emit fixed tool surfaces when
 * wired into an agent's bottom handle (or an MCP host's bottom handle):
 *   - `tool`        — ToolNode, exposes a custom downstream subgraph
 *   - `mcp-server`  — external MCP server or hosted bundle
 *   - `alarm`       — AlarmNode (4 alarm tools: schedule/list/cancel/update)
 *   - `filesystem`  — FilesystemNode (sandbox volume + upload_file tool)
 *   - `noclick`     — NoClickNode (runtime-discovered NoClick MCP tools)
 * Mirrors FlowCanvas.isValidConnection's BOTTOM_HANDLE_TYPES.
 */
export const STRUCTURAL_AGENT_TOOL_TYPES: ReadonlySet<string> = new Set([
    'tool',
    'mcp-server',
    'alarm',
    'filesystem',
    'noclick',
]);

/** Can this node type wire its 'top' into an agent's 'bottom' as a tool
 *  provider? THE rule — shared by isValidConnection and the agent drop target
 *  so the canvas can't accept a drop the validator would reject. */
export function canFeedAgentBottom(nodeType: string | undefined | null): boolean {
    return (
        (!!nodeType && STRUCTURAL_AGENT_TOOL_TYPES.has(nodeType)) ||
        isAgentToolProviderType(nodeType)
    );
}

let _wirableCatalog: { triggers: Array<{ nodeType: string; triggerOps: TriggerOperation[] }>; tools: string[] } | null = null;

/**
 * Node types wirable to an agent from the chat sidebar: dedicated trigger-*
 * types (minus the manual Run button) + integrations with ≥1 trigger
 * operation, and tool-provider-capable types — both operation-allowlist
 * providers (~58 integrations exposing node_op tools) AND the four
 * structural tool types in STRUCTURAL_AGENT_TOOL_TYPES. Schema walk over
 * every type (after loadAllNodeSchemas) — computed once and cached.
 */
export function getAgentWirableCatalog(): { triggers: Array<{ nodeType: string; triggerOps: TriggerOperation[] }>; tools: string[] } {
    if (_wirableCatalog) return _wirableCatalog;
    requireAllLoaded('getAgentWirableCatalog');
    const triggers: Array<{ nodeType: string; triggerOps: TriggerOperation[] }> = [];
    const tools: string[] = [];
    for (const nodeType of NODE_SCHEMA_TYPES) {
        if (nodeType.startsWith('trigger-') && nodeType !== 'trigger-run') {
            triggers.push({ nodeType, triggerOps: [] });
        } else {
            const triggerOps = getTriggerOperations(nodeType);
            if (triggerOps.length > 0) triggers.push({ nodeType, triggerOps });
        }
        if (isAgentToolProviderType(nodeType) || STRUCTURAL_AGENT_TOOL_TYPES.has(nodeType)) tools.push(nodeType);
    }
    _wirableCatalog = { triggers, tools };
    return _wirableCatalog;
}

/**
 * Credential info extracted from a node schema.
 * Used by template loading and workflow generation to determine what credentials a node needs.
 */
export interface NodeCredentialInfo {
    /** Provider key for getProviderConfigNormalized (e.g., 'google_sheets', 'slack') */
    providerKey: string;
    /** Array of accepted DB credential types (e.g., ['slack_oauth', 'slack_bot_token']) */
    acceptedTypes: string[];
    /** Display label for the credential (e.g., 'Google Account', 'Slack Workspace') */
    label: string;
}


/**
 * Extract a provider key from node type or credential schema.
 * E.g., 'automation-google-sheets' → 'google_sheets', 'automation-slack' → 'slack'
 */
function extractProviderKeyFromNodeType(nodeType: string): string {
    // Remove 'automation-' or 'trigger-' prefix and convert to snake_case
    return nodeType
        .replace(/^(automation|trigger)-/, '')
        .replace(/-/g, '_');
}

/**
 * Get a display label for a provider.
 * E.g., 'google_sheets' → 'Google Sheets', 'slack' → 'Slack'
 */
function getProviderLabel(providerKey: string): string {
    // Special cases for display names
    const labelMap: Record<string, string> = {
        'google_sheets': 'Google Account',
        'google_drive': 'Google Account',
        'gmail': 'Google Account',
        'google_calendar': 'Google Account',
        'google_tasks': 'Google Account',
        'google_contacts': 'Google Account',
        'google_docs': 'Google Account',
        'google_forms': 'Google Account',
        'google_slides': 'Google Account',
        'google_analytics': 'Google Account',
        'google_ads': 'Google Account',
        'google_business_profile': 'Google Account',
        'youtube': 'Google Account',
        'github': 'GitHub Account',
        'github_rest': 'GitHub Account',
        'slack': 'Slack Workspace',
        'airtable': 'Airtable Account',
        'stripe': 'Stripe Account',
        'notion': 'Notion Workspace',
        'linear': 'Linear Account',
        'discord': 'Discord Account',
        'outlook': 'Microsoft Account',
        'excel': 'Microsoft Account',
        'onedrive': 'Microsoft Account',
        'microsoft_todo': 'Microsoft Account',
        'word': 'Microsoft Account',
        'microsoft_teams': 'Microsoft Account',
        'microsoft': 'Microsoft Account',
        'hubspot': 'HubSpot Account',
        'affinity': 'Affinity Account',
        'nocodb': 'NocoDB Account',
        'basedash': 'Basedash Account',
        'salesforce': 'Salesforce Account',
        'jira': 'Jira Account',
        'shopify': 'Shopify Store',
        'dropbox': 'Dropbox Account',
        'mailchimp': 'Mailchimp Account',
        'typeform': 'Typeform Account',
        'canva': 'Canva Account',
        'twitter': 'Twitter Account',
        'linkedin': 'LinkedIn Account',
        'reddit': 'Reddit Account',
        'telegram': 'Telegram Bot',
        'phone': 'Phone Number',
        'instagram': 'Instagram Account',
        'instantly': 'Instantly Account',
        'tiktok': 'TikTok Account',
        'bluesky': 'Bluesky Account',
        'wordpress': 'WordPress Account',
    };

    if (labelMap[providerKey]) return labelMap[providerKey];

    // Default: Convert snake_case to Title Case
    return providerKey
        .split('_')
        .map(word => word.charAt(0).toUpperCase() + word.slice(1))
        .join(' ') + ' Account';
}

/**
 * The keys a stored credential of each of this node's credential classes may carry: the class's
 * `credential_type` const, its mapped type, and its lowercased raw schema title (legacy SDK-created
 * credentials stored the title verbatim, e.g. `instagrampageaccesstokencredential`).
 */
export function credentialKeysOf(nodeType: string): string[] {
    const schema = NODE_SCHEMAS[nodeType];
    const credProp = schema?.$defs ? schema.properties?.credentials : undefined;
    if (!credProp) return [];
    const refs: string[] = [];
    if (credProp.$ref) refs.push(credProp.$ref.split('/').pop()!);
    for (const entry of credProp.anyOf ?? []) {
        if (entry.$ref) refs.push(entry.$ref.split('/').pop()!);
    }
    const keys = new Set<string>();
    for (const title of refs) {
        const defn = schema.$defs[title];
        if (!defn) continue;
        keys.add(getCredentialTypeFromSchemaTitle(title));
        keys.add(title.toLowerCase());
        const constVal = defn.properties?.credential_type?.const;
        if (constVal) keys.add(constVal);
    }
    keys.delete('');
    return [...keys];
}

/**
 * Node type → the credential keys that wear its mark: each key goes to the first node schema (in NODE_SCHEMA_TYPES
 * order) declaring it among those `hasIcon` accepts. Serialized with the node catalog (credentialKeys) so credential
 * icons resolve without the schemas.
 */
export function credentialMarks(hasIcon: (nodeType: string) => boolean): Map<string, string[]> {
    requireAllLoaded('credentialMarks');
    const claimed = new Set<string>();
    const marks = new Map<string, string[]>();
    for (const type of NODE_SCHEMA_TYPES) {
        if (!hasIcon(type)) continue;
        const keys = credentialKeysOf(type).filter((key) => !claimed.has(key));
        if (!keys.length) continue;
        keys.forEach((key) => claimed.add(key));
        marks.set(type, keys);
    }
    return marks;
}

/**
 * Extract credential info from a node schema.
 * Returns info about what credentials the node requires, or undefined if no credentials needed.
 *
 * This function analyzes the schema's credentials property to determine:
 * - Provider key for OAuth lookup
 * - List of accepted credential types (OAuth, PAT, API key, etc.)
 * - Display label for the credential
 */
export function getNodeCredentialInfo(nodeType: string): NodeCredentialInfo | undefined {
    const schema = NODE_SCHEMAS[nodeType];
    if (!schema?.properties?.credentials) return undefined;

    const credentialProp = schema.properties.credentials;
    const $defs = schema.$defs || schema.definitions || {};

    // Resolve $ref to get the actual credential schema
    const resolveRef = (ref: string): any => {
        const path = ref.replace('#/$defs/', '').replace('#/definitions/', '');
        return $defs[path];
    };

    // Collect all credential schemas
    const credentialSchemas: Array<{ schema: any; title: string }> = [];

    if (credentialProp.$ref) {
        // Direct $ref - single credential type
        const credSchema = resolveRef(credentialProp.$ref);
        if (credSchema) {
            credentialSchemas.push({ schema: credSchema, title: credSchema.title || '' });
        }
    } else if (credentialProp.anyOf) {
        // anyOf pattern - multiple credential types (OAuth, PAT, etc.)
        for (const entry of credentialProp.anyOf) {
            if (entry.$ref) {
                const credSchema = resolveRef(entry.$ref);
                if (credSchema && credSchema.title) {
                    credentialSchemas.push({ schema: credSchema, title: credSchema.title });
                }
            }
        }
    }

    if (credentialSchemas.length === 0) return undefined;

    // Extract accepted types from all credential schemas
    const acceptedTypes: string[] = [];
    let oauthProvider: string | undefined;

    for (const { schema: credSchema, title } of credentialSchemas) {
        // Convert title to DB type using explicit map (e.g., 'SlackOAuthCredential' → 'slack_oauth')
        const dbType = getCredentialTypeFromSchemaTitle(title);
        acceptedTypes.push(dbType);

        // Check for OAuth provider marker
        if (credSchema['x-oauth-provider'] && !oauthProvider) {
            oauthProvider = credSchema['x-oauth-provider'];
        }
    }

    // Determine provider key:
    // 1. For Google services, use node-derived key (google_sheets, gmail, etc.) for service-specific scopes
    // 2. For non-Google OAuth services, use x-oauth-provider (e.g., 'microsoft' for outlook)
    // 3. Otherwise derive from node type
    const baseProviderKey = extractProviderKeyFromNodeType(nodeType);

    // Use oauthProvider for non-Google services that need it (e.g., outlook → microsoft)
    // Google services use service-specific keys for proper scope handling via PROVIDER_ALIASES
    const providerKey = (oauthProvider && oauthProvider !== 'google')
        ? oauthProvider
        : baseProviderKey;

    return {
        providerKey,
        acceptedTypes,
        label: getProviderLabel(providerKey),
    };
}

/**
 * Filters a node's config to only include fields that belong to the currently selected operation.
 * This is critical for nodes with discriminated unions (e.g., Google Sheets with read/write/append).
 *
 * When users switch between operations in the UI, we intentionally keep all fields to allow
 * easy switching. However, when sending to the backend, we must filter out fields from
 * non-selected operations to ensure proper schema validation.
 */
export function filterConfigForExecution(
    nodeType: string | undefined,
    config: Record<string, any>
): Record<string, any> {
    if (!config || typeof config !== 'object') return config;
    if (!nodeType) return config;

    const rootSchema = NODE_SCHEMAS[nodeType];
    if (!rootSchema) return config;

    // Extract config sub-schema (root schema has { properties: { config: {...} } })
    const configSchema = rootSchema?.properties?.config || rootSchema;

    // Resolve $refs from root schema's $defs
    const resolveRef = (ref: string): any => {
        const path = ref.replace('#/$defs/', '');
        return rootSchema?.$defs?.[path] || rootSchema?.definitions?.[path];
    };

    // If schema is a $ref, resolve it
    const resolvedSchema = configSchema?.$ref ? resolveRef(configSchema.$ref) : configSchema;
    if (!resolvedSchema) return config;

    // Check for anyOf/oneOf (discriminated union)
    const options = resolvedSchema?.oneOf || resolvedSchema?.anyOf || [];
    if (options.length === 0) return config;

    // Detect discriminator field (field with const values in all options)
    let discriminatorField: string | null = null;
    const valueToOptionIndex = new Map<string, number>();

    const firstOption = options[0].$ref ? resolveRef(options[0].$ref) : options[0];
    const firstProps = firstOption?.properties || {};

    for (const [fieldName, fieldProp] of Object.entries(firstProps) as [string, any][]) {
        const constValue = fieldProp?.const;
        if (!constValue) continue;

        let isDiscriminator = true;
        const values = new Map<string, number>();
        values.set(constValue, 0);

        for (let i = 1; i < options.length; i++) {
            const option = options[i].$ref ? resolveRef(options[i].$ref) : options[i];
            const prop = option?.properties?.[fieldName];
            if (!prop?.const) {
                isDiscriminator = false;
                break;
            }
            values.set(prop.const, i);
        }

        if (isDiscriminator && values.size === options.length) {
            discriminatorField = fieldName;
            values.forEach((idx, val) => valueToOptionIndex.set(val, idx));
            break;
        }
    }

    if (!discriminatorField) return config;

    // Get the discriminator value from config
    const discriminatorValue = config[discriminatorField];
    if (!discriminatorValue || !valueToOptionIndex.has(discriminatorValue)) return config;

    // Get the selected option's fields
    const optionIndex = valueToOptionIndex.get(discriminatorValue)!;
    const selectedOption = options[optionIndex].$ref
        ? resolveRef(options[optionIndex].$ref)
        : options[optionIndex];
    const selectedOptionFields = new Set(Object.keys(selectedOption?.properties || {}));

    // Collect all schema fields from all options
    const allSchemaFields = new Set<string>();
    options.forEach((opt: any) => {
        const resolved = opt.$ref ? resolveRef(opt.$ref) : opt;
        Object.keys(resolved?.properties || {}).forEach(key => allSchemaFields.add(key));
    });

    // Build filtered config: non-schema fields + selected option's fields only
    const filteredConfig: Record<string, any> = {};
    for (const [key, value] of Object.entries(config)) {
        if (!allSchemaFields.has(key) || selectedOptionFields.has(key)) {
            filteredConfig[key] = value;
        }
    }

    return filteredConfig;
}
