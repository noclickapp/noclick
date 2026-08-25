// Per-field "shortcut" actions rendered in the BuilderInputDrawer as an
// alternative to answering the agentic builder's <ask> with a value.
// Clicking one replies to the ask with a free-form message (no values)
// telling the agent what to do — the agent then uses its existing
// add_node/run_node/remove_node tools to provision the resource via a
// temporary node and resumes with the answer applied.
//
// Keyed by `${nodeType}::${fieldKey}`. Affordances are now DERIVED FROM THE
// NODE SCHEMAS, not hand-listed: every node's create operation declares
// `x-creates-resource` + `x-resource-type` (+ `x-resource-id-path`), and its
// resource-picker fields declare a matching `x-resource-type` on their
// `x-dynamic-options`. Any (dynamic field, create op) pair sharing a resource
// type in the same node gets a "Create new …" affordance automatically — so
// enabling one for a node is a schema annotation, with zero wiring here.
//
// OVERRIDES lets a node hand-tune the label/message when the schema-derived
// wording is awkward; it takes precedence over the generated entry.

import type { InputRequest } from '~/components/workflow/workflowGeneratorMock';
import { NODE_SCHEMAS } from '~/utils/nodeSchemas';

export interface FieldAffordance {
    label: string;
    message: string;
}

function createNewMessage(args: {
    resource: string;
    nodeType: string;
    operation: string;
    idDescription: string;
}): string {
    return (
        `Please create a new ${args.resource} for me to use here. ` +
        `Provision it with a temporary ${args.nodeType} node using ` +
        `the ${args.operation} operation, then set the resulting ` +
        `${args.idDescription} as the value for this field and ` +
        `remove the temporary node when done.`
    );
}

// ---------------------------------------------------------------------------
// Schema-driven derivation
// ---------------------------------------------------------------------------

interface CreateOp {
    operation: string;
    resourceType: string;
    label: string; // from x-display-name, e.g. "Create New Spreadsheet"
}

/** Resolve a node schema's operation variants, following the top-level
 *  `config` oneOf/anyOf and dereferencing `$defs` entries. */
function operationVariants(schema: any): any[] {
    if (!schema || typeof schema !== 'object') return [];
    const defs = schema.$defs || schema.definitions || {};
    const cfg = schema.properties?.config ?? schema;
    const union = cfg.oneOf || cfg.anyOf || schema.oneOf || schema.anyOf || [];
    const resolve = (v: any): any => {
        if (v && typeof v.$ref === 'string') {
            const name = v.$ref.split('/').pop();
            return name ? defs[name] ?? v : v;
        }
        return v;
    };
    return union.map(resolve).filter((v: any) => v && v.properties);
}

/** Human resource label from a resource type: drop the provider prefix and
 *  prettify, e.g. "google_spreadsheet" -> "spreadsheet", "sheet_tab" stays. */
function resourceLabel(resourceType: string): string {
    const parts = resourceType.split('_');
    const tail = parts.length > 1 ? parts.slice(1) : parts;
    return tail.join(' ');
}

/** Build the (nodeType::fieldKey -> affordance) map from the node schemas. */
function buildAffordances(): Record<string, FieldAffordance> {
    const out: Record<string, FieldAffordance> = {};

    for (const [nodeType, schema] of Object.entries(NODE_SCHEMAS)) {
        const variants = operationVariants(schema);
        if (!variants.length) continue;

        // resourceType -> the create op that produces it (first wins)
        const creators: Record<string, CreateOp> = {};
        for (const v of variants) {
            const op = v.properties?.operation;
            if (!op || !op['x-creates-resource']) continue;
            const resourceType = op['x-resource-type'];
            const operation = op.const ?? op.default;
            if (!resourceType || !operation || creators[resourceType]) continue;
            creators[resourceType] = {
                operation,
                resourceType,
                label: op['x-display-name'] || `Create new ${resourceLabel(resourceType)}`,
            };
        }
        if (!Object.keys(creators).length) continue;

        // resource-picker fields (x-dynamic-options + x-resource-type) whose
        // resource type has a creator in this same node.
        const seen = new Set<string>();
        for (const v of variants) {
            for (const [fieldKey, fieldSchema] of Object.entries<any>(v.properties || {})) {
                if (fieldKey === 'operation' || !fieldSchema || typeof fieldSchema !== 'object') continue;
                if (!fieldSchema['x-dynamic-options']) continue;
                const resourceType = fieldSchema['x-resource-type'];
                if (!resourceType) continue;
                const creator = creators[resourceType];
                if (!creator) continue;
                const key = `${nodeType}::${fieldKey}`;
                if (seen.has(key)) continue;
                seen.add(key);
                const resource = resourceLabel(resourceType);
                out[key] = {
                    label: creator.label,
                    message: createNewMessage({
                        resource,
                        nodeType,
                        operation: creator.operation,
                        idDescription: `${resource} ID`,
                    }),
                };
            }
        }
    }
    return out;
}

// Hand-tuned wording that beats the schema-derived default. Merged on top of
// the generated map (takes precedence). Keep minimal — prefer fixing the
// schema's x-display-name / x-resource-type over adding entries here.
const OVERRIDES: Record<string, FieldAffordance> = {};

let _cache: Record<string, FieldAffordance> | null = null;
function affordances(): Record<string, FieldAffordance> {
    if (_cache) return _cache;
    _cache = { ...buildAffordances(), ...OVERRIDES };
    return _cache;
}

export function getFieldAffordance(input: InputRequest | undefined): FieldAffordance | null {
    if (!input || input.type !== 'config' || !input.nodeType || !input.fieldKey) return null;
    return affordances()[`${input.nodeType}::${input.fieldKey}`] ?? null;
}

// Test/introspection helper: the full derived map.
export function _getAllFieldAffordances(): Record<string, FieldAffordance> {
    return affordances();
}
