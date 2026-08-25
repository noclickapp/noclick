/**
 * schemaFieldExtractor - Shared logic for extracting fields from JSON Schema.
 * Used by both NodeConfig (workflow editor) and SchemaConfigForm (workflow generation).
 *
 * This module contains the SINGLE SOURCE OF TRUTH for schema field extraction.
 * Any changes to how fields are extracted should be made here.
 */

import { NODE_SCHEMAS } from '~/utils/nodeSchemas';

// ============================================================================
// Types
// ============================================================================

export interface ExtractedField {
    key: string;
    prop: any;
    required: boolean;
}

export interface SchemaInfo {
    /** Root schema for the node type */
    rootSchema: any;
    /** Resolved config schema (after $ref resolution) */
    resolvedConfigSchema: any;
    /** OneOf/anyOf options (empty if not discriminated) */
    options: any[];
    /** Whether the schema has oneOf/anyOf */
    hasOptions: boolean;
    /** Discriminator info if detected */
    discriminator: {
        fieldName: string | null;
        valueToOptionIndex: Map<string, number>;
        optionToValue: Map<number, string>;
    };
    /** Whether a discriminator was detected */
    hasDiscriminator: boolean;
    /** Function to resolve $refs */
    resolveRef: (ref: string) => any;
}

// ============================================================================
// Schema Resolution
// ============================================================================

/**
 * Get the root schema for a node type.
 */
export function getNodeSchema(nodeType: string): any {
    return NODE_SCHEMAS[nodeType];
}

/**
 * Create a ref resolver for a root schema.
 */
export function createRefResolver(rootSchema: any): (ref: string) => any {
    return (ref: string) => {
        const path = ref.replace('#/$defs/', '').replace('#/definitions/', '');
        return rootSchema?.$defs?.[path] || rootSchema?.definitions?.[path];
    };
}

/**
 * Detect discriminator field in anyOf/oneOf options.
 * Returns the field name and mapping of const values to option indices.
 */
export function detectDiscriminator(options: any[], resolveRef: (ref: string) => any): {
    fieldName: string | null;
    valueToOptionIndex: Map<string, number>;
    optionToValue: Map<number, string>;
} {
    const result = {
        fieldName: null as string | null,
        valueToOptionIndex: new Map<string, number>(),
        optionToValue: new Map<number, string>()
    };

    if (options.length < 2) return result;

    // Find fields with const values that exist in all options
    const firstOption = options[0].$ref ? resolveRef(options[0].$ref) : options[0];
    const firstProps = firstOption?.properties || {};

    for (const [fieldName, fieldProp] of Object.entries(firstProps) as [string, any][]) {
        // Check if this field has a const value
        const constValue = fieldProp?.const;
        if (!constValue) continue;

        // Check if all other options also have this field with const values
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
            result.fieldName = fieldName;
            result.valueToOptionIndex = values;
            // Create reverse mapping
            values.forEach((idx, val) => result.optionToValue.set(idx, val));
            break;
        }
    }

    return result;
}

// getSchemaInfo is a pure function of the static NODE_SCHEMAS, yet it's called
// thousands of times per node-palette open (the search index calls it once per
// operation across ~9.5k operations, and each call re-runs createRefResolver +
// detectDiscriminator over every option — an O(operations²) blowup). Memoize by
// node type so the whole thing collapses to one parse per node per session.
const schemaInfoCache = new Map<string, SchemaInfo | null>();

/**
 * Get complete schema info for a node type.
 * This is the main entry point for understanding a node's schema structure.
 */
export function getSchemaInfo(nodeType: string): SchemaInfo | null {
    const cached = schemaInfoCache.get(nodeType);
    if (cached !== undefined) return cached;
    const info = computeSchemaInfo(nodeType);
    schemaInfoCache.set(nodeType, info);
    return info;
}

function computeSchemaInfo(nodeType: string): SchemaInfo | null {
    const rootSchema = getNodeSchema(nodeType);
    if (!rootSchema) return null;

    const resolveRef = createRefResolver(rootSchema);

    // Extract config schema from root schema
    // Root schema has structure: { properties: { config: {...}, credentials: {...} } }
    const configSchema = rootSchema?.properties?.config || rootSchema;

    // Resolve if config schema is a $ref
    const resolvedConfigSchema = configSchema?.$ref ? resolveRef(configSchema.$ref) : configSchema;
    if (!resolvedConfigSchema) return null;

    // Check for oneOf/anyOf
    const options = resolvedConfigSchema?.oneOf || resolvedConfigSchema?.anyOf || [];
    const hasOptions = options.length > 0;

    // Detect discriminator
    const discriminator = hasOptions ? detectDiscriminator(options, resolveRef) : {
        fieldName: null,
        valueToOptionIndex: new Map(),
        optionToValue: new Map()
    };
    const hasDiscriminator = discriminator.fieldName !== null;

    return {
        rootSchema,
        resolvedConfigSchema,
        options,
        hasOptions,
        discriminator,
        hasDiscriminator,
        resolveRef,
    };
}

// ============================================================================
// Field Extraction
// ============================================================================

/**
 * Get fields for a specific operation/option index.
 * This mirrors NodeConfig's getFieldsForCurrentOption() logic exactly.
 *
 * @param nodeType - The node type (e.g., 'automation-google-sheets')
 * @param selectedOptionIndex - The selected option index (for discriminated unions)
 * @param operation - The operation value (alternative to selectedOptionIndex)
 */
export function getFieldsForOption(
    nodeType: string,
    selectedOptionIndex?: number,
    operation?: string
): ExtractedField[] {
    const schemaInfo = getSchemaInfo(nodeType);
    if (!schemaInfo) return [];

    const { resolvedConfigSchema, options, hasOptions, hasDiscriminator, discriminator, resolveRef } = schemaInfo;

    // If operation is provided but not selectedOptionIndex, find the index
    let optionIndex = selectedOptionIndex ?? 0;
    if (operation && hasDiscriminator && discriminator.valueToOptionIndex.has(operation)) {
        optionIndex = discriminator.valueToOptionIndex.get(operation)!;
    }

    const fields: ExtractedField[] = [];

    if (hasOptions) {
        if (hasDiscriminator) {
            // Only get fields from the selected option
            const option = options[optionIndex];
            const resolved = option?.$ref ? resolveRef(option.$ref) : option;
            const props = resolved?.properties || {};
            const requiredFields = resolved?.required || [];

            for (const [key, prop] of Object.entries(props) as [string, any][]) {
                // Skip hidden discriminator fields
                if (key === discriminator.fieldName && prop['ui:hidden']) {
                    continue;
                }
                // Skip all hidden fields
                if (prop['ui:hidden']) {
                    continue;
                }
                fields.push({
                    key,
                    prop,
                    required: requiredFields.includes(key),
                });
            }
        } else {
            // No discriminator - show all fields from all options (legacy behavior)
            const seenKeys = new Set<string>();
            for (const option of options) {
                const resolved = option.$ref ? resolveRef(option.$ref) : option;
                const props = resolved?.properties || {};
                const requiredFields = resolved?.required || [];

                for (const [key, prop] of Object.entries(props) as [string, any][]) {
                    if (seenKeys.has(key)) continue;
                    if (prop['ui:hidden']) continue;
                    seenKeys.add(key);
                    fields.push({
                        key,
                        prop,
                        required: requiredFields.includes(key),
                    });
                }
            }
        }
    } else {
        // No oneOf/anyOf - use direct properties from resolved config schema
        const properties = resolvedConfigSchema.properties || {};
        const required = resolvedConfigSchema.required || [];

        for (const [key, prop] of Object.entries(properties) as [string, any][]) {
            if (prop['ui:hidden']) continue;
            fields.push({
                key,
                prop,
                required: required.includes(key),
            });
        }
    }

    return fields;
}

/**
 * A require-one-of constraint: an array of groups, each group an array of
 * alternatives, each alternative an array of field keys that must ALL be filled
 * to satisfy that alternative. A group is satisfied iff any one alternative is.
 * Sourced from the schema's `x-require-one-of` extension (see backend nodes).
 */
export type RequireOneOfGroups = string[][][];

/**
 * Get the `x-require-one-of` groups for the active operation of a node type.
 * Resolves the selected discriminated-union option (by index or operation
 * value), falling back to the root config schema for non-discriminated nodes.
 */
export function getRequireOneOfGroups(
    nodeType: string,
    selectedOptionIndex?: number,
    operation?: string,
): RequireOneOfGroups {
    const schemaInfo = getSchemaInfo(nodeType);
    if (!schemaInfo) return [];

    const { resolvedConfigSchema, options, hasDiscriminator, discriminator, resolveRef } = schemaInfo;

    let schemaNode = resolvedConfigSchema;
    if (hasDiscriminator) {
        let optionIndex = selectedOptionIndex ?? 0;
        if (operation && discriminator.valueToOptionIndex.has(operation)) {
            optionIndex = discriminator.valueToOptionIndex.get(operation)!;
        }
        const option = options[optionIndex];
        schemaNode = option?.$ref ? resolveRef(option.$ref) : option;
    }

    return schemaNode?.['x-require-one-of'] || [];
}

/**
 * Check if a node type uses operations (has anyOf/oneOf with discriminator).
 */
export function nodeTypeHasOperations(nodeType: string): boolean {
    const schemaInfo = getSchemaInfo(nodeType);
    return schemaInfo?.hasDiscriminator ?? false;
}

/**
 * Whether the user is asked to choose an operation for this node type — i.e.
 * whether NodeConfig shows the OperationPicker.
 *
 * False for a union every variant of which opts into `x-flatten-union`: the
 * schema author is treating the union as an implementation detail and the
 * discriminator is derived, not picked (AgentNode infers model_type from the
 * model string). Deliberately NOT keyed off `ui:hidden` on the discriminator —
 * ordinary multi-operation nodes hide their const discriminator inside each
 * variant too, because the picker already represents it.
 *
 * Shared with validateNode so "no action selected" is flagged exactly when
 * there was an action to select.
 */
export function nodeTypeOffersOperationChoice(nodeType: string): boolean {
    const schemaInfo = getSchemaInfo(nodeType);
    if (!schemaInfo?.hasOptions || !schemaInfo.hasDiscriminator) return false;
    return !schemaInfo.options.every((option) => {
        const ref = (option as { $ref?: string })?.$ref;
        const resolved = ref ? schemaInfo.resolveRef(ref) : option;
        return (resolved as { 'x-flatten-union'?: boolean })?.['x-flatten-union'] === true;
    });
}

/**
 * Check if a node type has any configurable fields.
 */
export function nodeTypeHasConfig(nodeType: string): boolean {
    const schemaInfo = getSchemaInfo(nodeType);
    return schemaInfo !== null;
}

/**
 * Get available operations for a node type (for discriminated unions).
 */
export function getAvailableOperations(nodeType: string): Array<{ value: string; index: number }> {
    const schemaInfo = getSchemaInfo(nodeType);
    if (!schemaInfo?.hasDiscriminator) return [];

    const operations: Array<{ value: string; index: number }> = [];
    schemaInfo.discriminator.optionToValue.forEach((value, index) => {
        operations.push({ value, index });
    });
    return operations;
}

/**
 * Get the option label for display.
 */
export function getOptionLabel(nodeType: string, optionIndex: number): string {
    const schemaInfo = getSchemaInfo(nodeType);
    if (!schemaInfo || !schemaInfo.hasOptions) return '';

    const option = schemaInfo.options[optionIndex];
    const resolved = option?.$ref ? schemaInfo.resolveRef(option.$ref) : option;

    // Try to get a nice label from the option
    if (resolved?.title) {
        // If title already has spaces (properly formatted from schema), use it as-is
        if (resolved.title.includes(' ')) {
            return resolved.title;
        }
        // Otherwise, remove "Config" suffix and clean up
        let label = resolved.title.replace(/Config$/, '');
        // Remove common node type prefixes
        label = label.replace(/^(GoogleCalendar|GoogleSheets|GoogleDrive|GithubRest|Github|Gmail|Airtable|Linear|Telegram|Reddit|Salesforce|YouTube|LinkedIn|HttpRequest|HN)/, '');
        // Add spaces before capitals and trim
        return label.replace(/([A-Z])/g, ' $1').trim();
    }

    if (resolved?.description) {
        // Use first sentence of description
        return resolved.description.split('.')[0];
    }

    // Fallback to discriminator value
    if (schemaInfo.hasDiscriminator) {
        const value = schemaInfo.discriminator.optionToValue.get(optionIndex);
        if (value) {
            return value.charAt(0).toUpperCase() + value.slice(1);
        }
    }

    return `Option ${optionIndex + 1}`;
}
