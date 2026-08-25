/**
 * Utility for validating workflow nodes and detecting incomplete configurations.
 * Used by IncompleteNodeNavigator to proactively warn users about nodes that need attention.
 */

import type { Edge, Node } from '@xyflow/react';
import { getSchemaInfo, getFieldsForOption, getRequireOneOfGroups, nodeTypeOffersOperationChoice, type RequireOneOfGroups } from '~/utils/schemaFieldExtractor';
import { hasUnconnectedCredentials, providerCredentialsMissing } from '~/components/workflow/NodeCredentials';
import { isAgentToolProviderType } from '~/utils/nodeSchemas';

/** Graph context for edge-dependent validation (agent tool-provider mode).
 *  Optional — callers without edges get plain per-node validation.
 *  Precomputed ONCE per validation pass (see buildNodeValidationContext) so
 *  per-node checks are O(1) instead of re-scanning nodes+edges per node. */
export interface NodeValidationContext {
    /** Ids of nodes currently wired into an agent's bottom handle as tool
     *  providers (qualifying types only). */
    wiredProviderIds: ReadonlySet<string>;
}

/**
 * Stable string key of the current provider wiring — sorted wired-provider
 * ids joined with '|'. Cheap to recompute on every edges-identity change
 * (xyflow rewrites the edges array on selection), and identical content
 * yields an identical string, letting callers memo the context object
 * content-stably so selection churn doesn't retrigger validation passes.
 */
export function computeWiredProviderIdsKey(nodes: Node[], edges: Edge[]): string {
    // Consumers: agents AND hosting-mode MCP nodes — providers wired into
    // either get provider-mode validation (allowlist + credentials only).
    const consumerIds = new Set(
        nodes.filter(n => n.type === 'agent' || n.type === 'mcp-server').map(n => n.id),
    );
    const byId = new Map(nodes.map(n => [n.id, n]));
    const wired = new Set<string>();
    for (const e of edges) {
        if (e.targetHandle !== 'bottom' || !consumerIds.has(e.target)) continue;
        const source = byId.get(e.source);
        if (source && isAgentToolProviderType(source.type)) wired.add(source.id);
    }
    return [...wired].sort().join('|');
}

/** Build a validation context from a wiring key (see computeWiredProviderIdsKey). */
export function contextFromWiringKey(key: string): NodeValidationContext {
    return { wiredProviderIds: new Set(key ? key.split('|') : []) };
}

/** Convenience for non-React callers: key + context in one step. */
export function buildNodeValidationContext(nodes: Node[], edges: Edge[]): NodeValidationContext {
    return contextFromWiringKey(computeWiredProviderIdsKey(nodes, edges));
}

// Node types that don't require configuration validation
const SKIP_VALIDATION_TYPES = new Set([
    'stickyNote',
]);

export interface NodeValidationIssue {
    type: 'missing_required_field' | 'missing_credentials' | 'missing_operation';
    message: string;
    fieldKey?: string;
}

export interface NodeValidationResult {
    isComplete: boolean;
    issues: NodeValidationIssue[];
}

/**
 * Check if a field value is considered "empty" for validation purposes.
 */
export function isFieldEmpty(value: unknown): boolean {
    if (value === undefined || value === null) return true;
    if (typeof value === 'string' && value.trim() === '') return true;
    if (Array.isArray(value) && value.length === 0) return true;
    return false;
}

export interface SchemaFieldProp {
    default?: unknown;
    anyOf?: Array<{ type?: string }>;
    title?: string;
}

/**
 * Check if a field has a default value in its schema. Optional[T] (anyOf with
 * null) counts — the implicit None default means the backend won't reject the
 * node for omitting it.
 */
export function hasDefaultValue(fieldProp: SchemaFieldProp): boolean {
    if ('default' in fieldProp) return true;
    const anyOf = fieldProp.anyOf;
    if (anyOf && anyOf.some(t => t.type === 'null')) return true;
    return false;
}

/**
 * Single definition of "this field needs the user's attention" — true iff the
 * field is required, has no schema default, isn't an auto-set discriminator,
 * and the node's config value for it is empty.
 *
 * Both `validateNode` (drives `configValid` / the navigator pill / the auto-
 * consumers (the incomplete pill, the Setup tab's derived steps)
 * (drives the guided-setup wizard) route through this. Keeping the rule in one
 * place is what stops the pill and the Setup tab from disagreeing about
 * whether anything is left to fill.
 */
export interface SchemaField {
    key: string;
    required: boolean;
    prop: SchemaFieldProp;
}

/**
 * Single definition of "is this field something the user is responsible for
 * filling in?" — required, no schema default, and not the discriminator
 * (which is either hidden / backend-derived or surfaced as its own UX, never
 * as a regular required field).
 *
 * Pass the field name returned by `getDiscriminatorFieldName(nodeType)`; pass
 * `null` (or omit) for nodes without a discriminator.
 *
 * Deliberately answers ONLY the schema-shape question, not the live "is it
 * empty right now?" question. The two get composed at call sites:
 *   • validateNode → AND with isFieldEmpty (to flag missing required fields)
 *   • buildRequiredSteps → use this alone (to enumerate the wizard's steps)
 *   • isStepFilled → use isFieldEmpty alone on the already-built step
 * Keeping them separate is what stops the wizard step from vanishing mid-edit
 * the instant the user types a valid character.
 */
export function isFieldRequired(
    field: SchemaField,
    discriminatorField?: string | null,
): boolean {
    if (!field.required) return false;
    if (hasDefaultValue(field.prop)) return false;
    if (discriminatorField && field.key === discriminatorField) return false;
    return true;
}

/**
 * Get the operation value from node data for discriminated unions.
 * operation is top-level metadata on data, not a config field.
 */
function getNodeOperation(nodeData: Record<string, unknown>): string | undefined {
    return nodeData?.operation as string | undefined;
}

export interface RequireOneOfResult {
    /** Groups where no alternative is fully satisfied. */
    unsatisfiedGroups: RequireOneOfGroups;
    /** Empty field keys belonging to an unsatisfied group — the ones to flag. */
    attentionKeys: Set<string>;
}

/**
 * Evaluate `x-require-one-of` groups against a config. A group is satisfied iff
 * some alternative has ALL its fields non-empty. Single source of truth for the
 * either-or rule, shared by the canvas validator and the config panel so the
 * amber "needs one of these" hint and the run-blocking error never disagree.
 */
export function evaluateRequireOneOf(
    groups: RequireOneOfGroups | undefined,
    config: Record<string, unknown>,
): RequireOneOfResult {
    const unsatisfiedGroups: RequireOneOfGroups = [];
    const attentionKeys = new Set<string>();
    if (!Array.isArray(groups)) return { unsatisfiedGroups, attentionKeys };

    for (const group of groups) {
        if (!Array.isArray(group) || group.length === 0) continue;
        const satisfied = group.some(
            alt => Array.isArray(alt) && alt.length > 0 && alt.every(k => !isFieldEmpty(config[k])),
        );
        if (!satisfied) {
            unsatisfiedGroups.push(group);
            for (const alt of group) {
                for (const k of alt) {
                    if (isFieldEmpty(config[k])) attentionKeys.add(k);
                }
            }
        }
    }
    return { unsatisfiedGroups, attentionKeys };
}

/**
 * Human-readable description of a require-one-of group, e.g.
 * "Video ID or Address" or "Region Place ID or Latitude + Longitude + Radius".
 */
export function describeRequireOneOfGroup(
    group: string[][],
    titleOf: (key: string) => string,
): string {
    return group.map(alt => alt.map(titleOf).join(' + ')).join(' or ');
}

/**
 * Validate a single node's configuration.
 * Returns whether the node is complete and any issues found.
 */
export function validateNode(node: Node, context?: NodeValidationContext): NodeValidationResult {
    const issues: NodeValidationIssue[] = [];

    // Skip validation for certain node types
    if (!node.type || SKIP_VALIDATION_TYPES.has(node.type)) {
        return { isComplete: true, issues: [] };
    }

    const nodeData = (node.data || {}) as Record<string, unknown>;
    // Config fields are nested under data.config (authoritative). Metadata like
    // operation and credentialIds stays top-level on data.
    const config = (nodeData.config || {}) as Record<string, unknown>;
    const credentialIds = (nodeData.credentialIds || {}) as Record<string, string>;

    // Tool-provider mode (wired into an agent's or MCP server's bottom
    // handle): the node exposes allowlisted operations instead of running
    // one, so operation/field validation doesn't apply — it needs at least
    // one action selected, and credentials only if some allowlisted action
    // requires them (allowlist-aware check).
    if (context && context.wiredProviderIds.has(node.id)) {
        if (providerCredentialsMissing(node.type, credentialIds, nodeData)) {
            issues.push({
                type: 'missing_credentials',
                message: 'Credentials required',
            });
        }
        const ops = config.agent_tool_operations;
        if (!Array.isArray(ops) || ops.length === 0) {
            issues.push({
                type: 'missing_required_field',
                message: 'Select at least one action to expose to the agent',
                fieldKey: 'agent_tool_operations',
            });
        }
        return { isComplete: issues.length === 0, issues };
    }

    // Check for missing credentials (pass nodeData for agent nodes which need model info)
    if (hasUnconnectedCredentials(node.type, credentialIds, nodeData)) {
        issues.push({
            type: 'missing_credentials',
            message: 'Credentials required',
        });
    }

    // Get schema info for this node type
    const schemaInfo = getSchemaInfo(node.type);
    if (!schemaInfo) {
        // No schema means no validation needed (e.g., custom nodes)
        return { isComplete: issues.length === 0, issues };
    }

    // Operation for discriminated unions lives top-level on data, not in
    // data.config. The discriminator name comes from the schema so the
    // skip-rule isn't tied to specific field names.
    const operation = getNodeOperation(nodeData);
    const discriminatorField = schemaInfo.discriminator.fieldName;

    // No action picked on a node that offers a choice of them. Nothing else
    // catches this: the discriminator is excluded from the required-field loop
    // below (it is surfaced as its own picker UI, not a regular field), so a
    // node sitting with no operation looked complete everywhere — the pill, the
    // canvas border, the Run gate — and then failed at execution with an error
    // about the operation being missing, phrased for a developer.
    //
    // Only when the schema actually offers a choice — the same predicate that
    // decides whether NodeConfig shows the picker. Single-purpose nodes have no
    // discriminator, and a flattened union (the agent's inferred model_type)
    // derives its discriminator rather than asking for it.
    if (!operation && nodeTypeOffersOperationChoice(node.type)) {
        issues.push({
            type: 'missing_operation',
            message: 'Choose an action',
            fieldKey: discriminatorField ?? undefined,
        });
        // Stop here. Which fields this node needs depends entirely on the
        // action, and getFieldsForOption falls back to option 0 when none is
        // selected — so continuing would report the FIRST action's requirements
        // as though they were this node's. A Google Sheets node with no action
        // picked was asking for a spreadsheet before anyone had said whether it
        // was reading, appending or creating one; worse, filling it could
        // satisfy validation for a field the eventual action never uses.
        return { isComplete: false, issues };
    }

    const fields = getFieldsForOption(node.type, undefined, operation);

    for (const field of fields) {
        if (!isFieldRequired(field, discriminatorField)) continue;
        if (!isFieldEmpty(config[field.key])) continue;
        const label = field.prop.title || field.key;
        issues.push({
            type: 'missing_required_field',
            message: `${label} is required`,
            fieldKey: field.key,
        });
    }

    // Either-or constraints: flag groups where no alternative is satisfied.
    const oneOfGroups = getRequireOneOfGroups(node.type, undefined, operation);
    if (oneOfGroups.length > 0) {
        const titleOf = (key: string) =>
            fields.find(f => f.key === key)?.prop.title || key;
        const { unsatisfiedGroups } = evaluateRequireOneOf(oneOfGroups, config);
        for (const group of unsatisfiedGroups) {
            issues.push({
                type: 'missing_required_field',
                message: `Provide ${describeRequireOneOfGroup(group, titleOf)}`,
                fieldKey: group[0]?.[0],
            });
        }
    }

    return {
        isComplete: issues.length === 0,
        issues,
    };
}

/**
 * Get all nodes that have incomplete configurations.
 * Returns nodes filtered to only those with validation issues.
 */
export function getIncompleteNodes(nodes: Node[], context?: NodeValidationContext): Node[] {
    return nodes.filter(node => {
        // Skip cursor nodes (collaborative editing)
        if (node.id.startsWith('cursor-')) return false;

        const result = validateNode(node, context);
        return !result.isComplete;
    });
}

/**
 * Get a summary of issues for a node.
 * Returns a short human-readable string.
 */
export function getNodeIssueSummary(node: Node, context?: NodeValidationContext): string {
    const result = validateNode(node, context);
    if (result.isComplete) return '';

    const missingFields = result.issues.filter(i => i.type === 'missing_required_field');
    const missingCreds = result.issues.filter(i => i.type === 'missing_credentials');
    const missingOperation = result.issues.some(i => i.type === 'missing_operation');

    const parts: string[] = [];

    // First: with no action picked there are no per-operation fields to report,
    // so this is the whole answer for such a node.
    if (missingOperation) {
        parts.push('no action selected');
    }

    if (missingCreds.length > 0) {
        parts.push('credentials needed');
    }

    if (missingFields.length > 0) {
        if (missingFields.length === 1) {
            parts.push(`${missingFields[0].fieldKey} required`);
        } else {
            parts.push(`${missingFields.length} fields required`);
        }
    }

    return parts.join(', ');
}
