// The config panel's instant (AJV) validation, as a pure function of the node's
// schema, its saved config and its COMMITTED operation. Lifted out of NodeConfig
// so the verdict can't depend on panel UI state (the picker's index starts at 0
// for a frame, which judged every trigger against its node's first action).

import Ajv2020 from 'ajv/dist/2020';
import addFormats from 'ajv-formats';
import { getSchemaInfo } from '~/utils/schemaFieldExtractor';
import { evaluateRequireOneOf, describeRequireOneOfGroup } from '~/utils/workflowNodeValidation';
import { tikTokDisclosureError } from '~/utils/tikTokPublishing';

export interface ConfigFormError {
    message: string;
    fieldKey?: string;      // For field-related errors, the field key to scroll to
    fieldLabel?: string;    // Human-readable field name
    type: 'field' | 'credentials' | 'general';
}

export interface ConfigFormValidation {
    valid: boolean;
    errors: ConfigFormError[];
}

/** An IANA zone name the scheduler can evaluate — it resolves zones with the same Intl data. */
export function isValidTimeZone(value: string): boolean {
    try {
        new Intl.DateTimeFormat('en-US', { timeZone: value });
        return true;
    } catch {
        return false;
    }
}

// IMPORTANT: Use Ajv2020 class for draft-2020-12 schemas
const ajv = new Ajv2020({
    allErrors: true,
    strict: false,  // Allow non-standard keywords like "ui:widget"
    validateFormats: true,  // Enable format validation (email, uri, etc.)
    coerceTypes: true,  // Coerce strings to booleans/numbers (e.g., "true" -> true)
});
addFormats(ajv);
ajv.addFormat('timezone', { type: 'string', validate: isValidTimeZone });

/**
 * Evaluate a ui:show-if condition against the current config.
 * Supports:
 *   { anyOf: [...] }         — passes if ANY sub-condition passes (OR compound)
 *   { field, contains }      — single substring match
 *   { field, containsAny }   — match ANY of the substrings (OR)
 *   { field, containsAll }   — match ALL of the substrings (AND) — pattern-based, future-proof
 *   { field, notContains }   — AND the field must NOT contain this string
 */
export function evaluateShowIf(showIf: any, config: Record<string, any>): boolean {
    if (showIf.anyOf) {
        return (showIf.anyOf as any[]).some(sub => evaluateShowIf(sub, config));
    }
    const condVal = String(config[showIf.field] ?? '').toLowerCase();
    let passes: boolean;
    if (showIf.containsAny) {
        passes = (showIf.containsAny as string[]).some(s => condVal.includes(s.toLowerCase()));
    } else if (showIf.containsAll) {
        passes = (showIf.containsAll as string[]).every(s => condVal.includes(s.toLowerCase()));
    } else if (showIf.contains) {
        passes = condVal.includes(showIf.contains.toLowerCase());
    } else {
        return false;
    }
    if (!passes) return false;
    if (showIf.notContains) {
        if (condVal.includes((showIf.notContains as string).toLowerCase())) return false;
    }
    return true;
}

/**
 * Validate a node's config for the operation it will actually run. Only the
 * fields of that operation that are currently visible (ui:show-if) are judged,
 * through the same lens as the runtime parse (`runtime_config_view`): a null
 * or "" on a field with a default is unset, so the default applies.
 */
export function validateConfigForm(
    nodeType: string,
    config: Record<string, any>,
    operation: string | undefined,
): ConfigFormValidation {
    const info = getSchemaInfo(nodeType);
    if (!info) {
        return { valid: false, errors: [{ message: 'No schema found for this node type', type: 'general' }] };
    }
    const { rootSchema, resolvedConfigSchema, options, hasDiscriminator, discriminator, resolveRef } = info;
    const discriminatorHidden = hasDiscriminator && options.every((option: any) => {
        const resolved = option.$ref ? resolveRef(option.$ref) : option;
        return resolved?.['x-flatten-union'] === true;
    });

    let activeSchema = resolvedConfigSchema;
    if (options.length > 0 && hasDiscriminator && !discriminatorHidden) {
        // Which fields apply depends entirely on the action, so without one
        // there is nothing to judge but the missing action itself (as the
        // canvas validator says).
        const optionIndex = operation ? discriminator.valueToOptionIndex.get(operation) : undefined;
        if (optionIndex === undefined) {
            return { valid: false, errors: [{ message: 'Choose an action', type: 'general' }] };
        }
        const selectedOption = options[optionIndex];
        activeSchema = (selectedOption?.$ref ? resolveRef(selectedOption.$ref) : selectedOption) || resolvedConfigSchema;
    } else if (options.length > 0) {
        // Merge all variants' fields so validation matches the flattened UI.
        const mergedProps: Record<string, any> = {};
        const mergedRequired: string[] = [];
        options.forEach((option: any) => {
            const resolved = option.$ref ? resolveRef(option.$ref) : option;
            Object.entries(resolved?.properties || {}).forEach(([k, v]) => {
                if (!(k in mergedProps)) mergedProps[k] = v;
            });
            (resolved?.required || []).forEach((f: string) => {
                if (!mergedRequired.includes(f)) mergedRequired.push(f);
            });
        });
        activeSchema = { ...resolvedConfigSchema, properties: mergedProps, required: mergedRequired };
    }

    // Build validation schema for the active operation only
    // Exclude fields hidden by ui:show-if conditions
    const allProperties = activeSchema?.properties || {};
    const visibleProperties: Record<string, any> = {};
    const allRequired = activeSchema?.required || [];
    for (const [key, prop] of Object.entries(allProperties) as [string, any][]) {
        const showIf = prop['ui:show-if'];
        if (showIf) {
            if (!evaluateShowIf(showIf, config)) {
                continue; // skip hidden fields
            }
        }
        visibleProperties[key] = prop;
        if (prop['x-enum-allow-custom']) {
            // The enum is the picker's suggestions, not the set the backend accepts.
            visibleProperties[key] = { ...prop };
            delete visibleProperties[key].enum;
        }
    }
    const visibleRequired = allRequired.filter((f: string) => f in visibleProperties);

    const validationSchema = {
        type: 'object',
        properties: visibleProperties,
        required: visibleRequired,
        $defs: rootSchema?.$defs || {},
        definitions: rootSchema?.definitions || {}
    };

    // Preprocess config: parse JSON string values for fields that expect arrays or
    // objects (e.g., person_titles: "[\"CEO\",\"Owner\"]" → ["CEO","Owner"]), as the
    // runtime does for the fields that take JSON text. For
    // ui:widget="list" fields, also coerce plain/comma-separated strings to
    // arrays so the banner doesn't flag a populated single recipient as
    // invalid — the list widget shows that string as one item, so validation
    // must agree.
    const preprocessed = { ...config };
    for (const [key, prop] of Object.entries(visibleProperties) as [string, any][]) {
        const val = preprocessed[key];
        if ((val === null || val === '') && 'default' in prop) {
            delete preprocessed[key];
            continue;
        }
        if (typeof val !== 'string') continue;
        // A reference/expression ({{ ... }}) resolves server-side; don't split or
        // coerce it (a comma inside `$('x').split(',')` isn't a list separator).
        if (val.includes('{{')) continue;
        const fieldOptions = prop.anyOf || prop.oneOf || (prop.type === 'array' || prop.type === 'object' ? [prop] : []);
        const expectsArray = fieldOptions.some((opt: any) => opt.type === 'array');
        const expectsObject = fieldOptions.some((opt: { type?: string }) => opt.type === 'object');
        if ((expectsArray && val.startsWith('[')) || (expectsObject && val.startsWith('{'))) {
            try { preprocessed[key] = JSON.parse(val); } catch { /* leave as-is */ }
        } else if (expectsArray && prop['ui:widget'] === 'list' && val.trim()) {
            preprocessed[key] = val.split(',').map((s: string) => s.trim()).filter(Boolean);
        }
    }

    const validate = ajv.compile(validationSchema);
    const ajvValid = validate(preprocessed);

    const validationErrors: ConfigFormError[] = [];
    const fieldsWithErrors = new Set<string>(); // Track fields already reported
    const labelOf = (field: string) => activeSchema?.properties?.[field]?.title || field;

    // Collect AJV validation errors
    if (!ajvValid) {
        // Filter out sub-errors from anyOf/oneOf branches — only keep the parent error
        // e.g., for anyOf: [{type: "array"}, {type: "null"}], AJV produces:
        //   1. type error for array branch (schemaPath: .../anyOf/0/type)
        //   2. type error for null branch (schemaPath: .../anyOf/1/type)
        //   3. parent anyOf error (schemaPath: .../anyOf)
        // We only want #3 to avoid duplicate rows per field
        const filteredErrors = (validate.errors || []).filter(err =>
            !err.schemaPath || !/\/(anyOf|oneOf)\/\d+/.test(err.schemaPath)
        );
        // Helper: extract top-level field name from instancePath (e.g., "/foo/0/bar" → "foo")
        const rootField = (path: string | undefined) => path?.replace(/^\//, '').split('/')[0] || '';

        for (const err of filteredErrors) {
            // A field holding a reference/expression ({{ ... }}) is resolved
            // server-side; its type/format/enum is only knowable after resolution,
            // so don't flag it as invalid here.
            const errField = err.keyword === 'required'
                ? err.params?.missingProperty
                : rootField(err.instancePath);
            const rawVal = errField ? config[errField] : undefined;
            if (typeof rawVal === 'string' && rawVal.includes('{{')) continue;
            if (err.keyword === 'anyOf' || err.keyword === 'oneOf') {
                const field = rootField(err.instancePath);
                if (field && !fieldsWithErrors.has(field)) {
                    fieldsWithErrors.add(field);
                    const fieldSchema = activeSchema?.properties?.[field];
                    const fieldOptions = fieldSchema?.anyOf || fieldSchema?.oneOf || [];
                    const expectedTypes = fieldOptions
                        .map((opt: any) => opt.type)
                        .filter((t: string) => t && t !== 'null');
                    const message = expectedTypes.length > 0
                        ? `must be ${expectedTypes.join(' or ')}`
                        : 'has invalid value';
                    validationErrors.push({ message, fieldKey: field, fieldLabel: labelOf(field), type: 'field' });
                }
                continue;
            }
            if (err.keyword === 'required') {
                const missing = err.params.missingProperty;
                if (fieldsWithErrors.has(missing)) continue;
                fieldsWithErrors.add(missing);
                validationErrors.push({ message: 'is required', fieldKey: missing, fieldLabel: labelOf(missing), type: 'field' });
            } else if (err.keyword === 'minLength') {
                const field = rootField(err.instancePath) || 'field';
                if (fieldsWithErrors.has(field)) continue;
                fieldsWithErrors.add(field);
                validationErrors.push({ message: 'is required', fieldKey: field, fieldLabel: labelOf(field), type: 'field' });
            } else if (err.keyword === 'pattern') {
                const field = rootField(err.instancePath) || 'field';
                if (fieldsWithErrors.has(field)) continue;
                fieldsWithErrors.add(field);
                validationErrors.push({ message: 'has invalid format', fieldKey: field, fieldLabel: labelOf(field), type: 'field' });
            } else if (err.keyword === 'format') {
                const field = rootField(err.instancePath) || 'field';
                if (fieldsWithErrors.has(field)) continue;
                fieldsWithErrors.add(field);
                validationErrors.push({ message: `must be a valid ${err.params?.format || 'value'}`, fieldKey: field, fieldLabel: labelOf(field), type: 'field' });
            } else if (err.keyword === 'type') {
                const field = rootField(err.instancePath) || 'field';
                if (fieldsWithErrors.has(field)) continue;
                // Empty string on a number/integer field means "use backend default" — not an error
                if ((err.params?.type === 'integer' || err.params?.type === 'number') && config[field] === '') {
                    continue;
                }
                fieldsWithErrors.add(field);
                const expectedType = err.params?.type || 'correct type';
                validationErrors.push({ message: `must be ${expectedType}`, fieldKey: field, fieldLabel: labelOf(field), type: 'field' });
            } else if (err.keyword === 'enum') {
                const field = rootField(err.instancePath);
                if (field) {
                    if (fieldsWithErrors.has(field)) continue;
                    fieldsWithErrors.add(field);
                    const fieldSchema = activeSchema?.properties?.[field];
                    // Get allowed values from err.params or the field's items schema
                    const allowed: string[] = err.params?.allowedValues
                        || fieldSchema?.items?.enum
                        || fieldSchema?.enum
                        || [];
                    const MAX_SHOWN = 8;
                    let message: string;
                    if (allowed.length === 0) {
                        message = 'has invalid value';
                    } else if (allowed.length <= MAX_SHOWN) {
                        message = `must be one of: ${allowed.join(', ')}`;
                    } else {
                        message = `must be one of: ${allowed.slice(0, MAX_SHOWN).join(', ')} (+${allowed.length - MAX_SHOWN} more)`;
                    }
                    validationErrors.push({ message, fieldKey: field, fieldLabel: labelOf(field), type: 'field' });
                }
            } else {
                const field = rootField(err.instancePath);
                if (field) {
                    if (fieldsWithErrors.has(field)) continue;
                    fieldsWithErrors.add(field);
                    validationErrors.push({ message: err.message || 'has invalid value', fieldKey: field, fieldLabel: labelOf(field), type: 'field' });
                } else {
                    validationErrors.push({ message: err.message || 'Invalid value', type: 'general' });
                }
            }
        }
    }

    // Additional check: required string fields that are empty
    // AJV's "required" only checks if property exists, not if it's non-empty
    // Use visibleRequired/visibleProperties to skip hidden fields
    for (const fieldName of visibleRequired) {
        // Skip if AJV already reported this field
        if (fieldsWithErrors.has(fieldName)) continue;

        const fieldSchema = visibleProperties[fieldName];
        // Check string fields that are empty (AJV doesn't catch this)
        if (fieldSchema?.type === 'string' && !fieldSchema?.default) {
            const value = config[fieldName];
            if (value === undefined || value === null || (typeof value === 'string' && value.trim() === '')) {
                validationErrors.push({ message: 'is required', fieldKey: fieldName, fieldLabel: labelOf(fieldName), type: 'field' });
            }
        }
    }

    // Either-or constraints: flag any group with no satisfied alternative.
    const oneOfGroups = activeSchema?.['x-require-one-of'];
    if (Array.isArray(oneOfGroups) && oneOfGroups.length > 0) {
        const { unsatisfiedGroups } = evaluateRequireOneOf(oneOfGroups, config);
        for (const group of unsatisfiedGroups) {
            const firstKey = group[0]?.[0];
            if (firstKey) fieldsWithErrors.add(firstKey);
            validationErrors.push({
                message: `Provide ${describeRequireOneOfGroup(group, labelOf)}`,
                fieldKey: firstKey,
                fieldLabel: firstKey ? labelOf(firstKey) : undefined,
                type: 'field',
            });
        }
    }

    if (nodeType === 'automation-tiktok' && ['direct_post_video', 'direct_post_photo'].includes(operation || '')) {
        const disclosureError = tikTokDisclosureError(config);
        if (disclosureError) validationErrors.push({ message: disclosureError, type: 'general' });
    }
    return { valid: validationErrors.length === 0, errors: validationErrors };
}
