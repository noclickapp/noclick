// Lightweight node-type predicates backed by the slim generated nodeMeta.json
// (~36KB) instead of the full schema registry (~9MB of JSON). Import from here —
// never from utils/nodeSchemas — in weight-sensitive chunks (marketing previews,
// the fork canvas, edge components) so they don't drag every node schema into
// their bundle. Both artifacts are emitted by the same generator run
// (backend/scripts/generate_socket_types.py), so they cannot drift.

import nodeMetaJson from '~/schemas/nodeMeta.json';

interface NodeMetaEntry {
    agentToolProvider?: boolean;
    triggerOperations?: string[];
}

const NODE_META: Record<string, NodeMetaEntry> = (
    nodeMetaJson as { types: Record<string, NodeMetaEntry> }
).types;

/**
 * The separate image/audio/video interface nodes were merged into the universal
 * File/Multimedia node (interface-file) in 2026-07. Resolve those legacy types to
 * it so pre-merge saved workflows still find a schema. Aliases resolve on property
 * READ only — Object.keys/values/entries over NODE_SCHEMAS stay clean (no legacy
 * keys leak into node listings / SDK bridge / credential scans).
 */
export const LEGACY_NODE_TYPE_ALIASES: Record<string, string> = {
    'interface-image': 'interface-file',
    'interface-audio': 'interface-file',
    'interface-video': 'interface-file',
    // 2026-07: the form trigger + config form merged into the unified form node.
    'trigger-form-input': 'interface-form',
    'interface-config-form': 'interface-form',
};

/** Canonical node type, resolving legacy aliases (mirrors backend resolve_node_type).
 *  Saved graphs may still carry pre-merge type strings; type checks against
 *  specific node types should compare the resolved value. */
export function resolveNodeType(nodeType: string): string {
    return LEGACY_NODE_TYPE_ALIASES[nodeType] ?? nodeType;
}

/**
 * Whether a node type can act as an agent tool provider — i.e. be wired to
 * an AI agent's bottom handle to expose its operations as node_op tools.
 * Stamped into the generated schema by the backend predicate
 * (nodes/agent/node_op_tools.py:node_supports_op_tools).
 */
export function isAgentToolProviderType(nodeType: string | undefined | null): boolean {
    return !!(nodeType && NODE_META[resolveNodeType(nodeType)]?.agentToolProvider === true);
}

/**
 * Whether a node, as currently configured, starts workflow runs on an external
 * event: dedicated trigger-* types always do; integration nodes do when their
 * selected operation is stamped `x-is-trigger` in the generated schema.
 */
export function isTriggerSource(
    nodeType: string | undefined | null,
    operation: string | undefined | null,
): boolean {
    if (!nodeType) return false;
    // Saved graphs may carry pre-merge types (trigger-form-input, interface-config-form)
    nodeType = resolveNodeType(nodeType);
    if (nodeType.startsWith('trigger-')) return true;
    // The unified form node mints a public form URL whose submissions start runs.
    if (nodeType === 'interface-form') return true;
    if (!operation) return false;
    return NODE_META[nodeType]?.triggerOperations?.includes(operation) ?? false;
}
