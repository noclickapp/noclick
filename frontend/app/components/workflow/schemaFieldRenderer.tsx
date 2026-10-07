/**
 * Shared choice controls for native config forms and the legacy generation renderer.
 *
 * Provides two variants:
 * - 'editor': Full-featured with DroppableTextField for drag-drop support
 * - 'generation': Simplified for workflow generation setup panel
 */

import type { ReactElement } from 'react';
import { renderSchemaWidget, hasRegisteredWidget, type WidgetRenderProps } from './schemaWidgetRegistry';
import { MultiSelectEnumField } from './MultiSelectEnumField';
import { SearchableEnumField } from './SearchableEnumField';
import { enumLabel, fieldAllowsNull, fieldValueSchema, numericFieldValue } from '~/utils/schemaFieldValues';

// Re-export widget registry for consumers that need it
export { renderSchemaWidget, hasRegisteredWidget, type WidgetRenderProps } from './schemaWidgetRegistry';

// ============================================================================
// Types
// ============================================================================

export interface SchemaFieldRenderOptions {
    /** Field key in the config */
    fieldKey: string;
    /** JSON Schema property definition */
    fieldSchema: any;
    /** Current value */
    value: any;
    /** Change handler */
    onChange: (key: string, value: any) => void;
    /** Whether field value is loading */
    isLoading?: boolean;
    /** Variant: 'editor' for NodeConfig, 'generation' for workflow generation */
    variant?: 'editor' | 'generation';
    /** Full config for sibling field access */
    config?: Record<string, any>;
}

// ============================================================================
// Styling
// ============================================================================

const editorInputClasses = "w-full px-3 py-2 text-sm bg-foreground/[0.02] border border-border dark:border-white/[0.05] rounded-lg text-foreground/80 placeholder:text-[hsl(var(--placeholder))] focus:outline-none focus:border-border dark:focus:border-white/[0.15] transition-colors";

const generationInputClasses = "w-full px-3 py-2 rounded-lg border border-border dark:border-white/[0.08] bg-foreground/[0.03] text-foreground text-sm outline-none placeholder:text-[hsl(var(--placeholder))] focus:border-foreground/20 focus:bg-foreground/[0.05]";

/** DOM option values are indices; saved values retain their schema types. */
export function renderSchemaChoice({ fieldKey, fieldSchema, value, onChange }: SchemaFieldRenderOptions, className: string): ReactElement | null {
    const prop = fieldValueSchema(fieldSchema);
    const expression = typeof value === 'string' && value.includes('{{');
    const labels = prop.enumNames ?? prop.enumLabels ?? prop.items?.enumNames ?? prop.items?.enumLabels;
    if (prop.type === 'array' && (Array.isArray(prop.enum) || Array.isArray(prop.items?.enum)) && !expression) {
        return <MultiSelectEnumField fieldKey={fieldKey} value={Array.isArray(value) ? value : []}
            enumValues={prop.enum ?? prop.items.enum} enumLabels={labels} onChange={onChange}
            placeholder={prop['ui:placeholder'] || prop.placeholder || prop.description || 'Select one or more...'} />;
    }
    const isEnum = prop.type !== 'array' && Array.isArray(prop.enum);
    if (!isEnum && (prop.type !== 'boolean' || expression)) return null;
    const options = isEnum ? [...prop.enum] : [true, false];
    if (fieldAllowsNull(fieldSchema) && !options.includes(null)) options.push(null);
    const optionLabels = options.map((option, index) => !isEnum && typeof option === 'boolean'
        ? option ? 'Yes' : 'No' : enumLabel(option, index, labels));
    if (isEnum && prop['x-enum-searchable'] === true) {
        return <SearchableEnumField fieldKey={fieldKey} value={value} enumValues={options}
            enumLabels={optionLabels} onChange={onChange}
            placeholder={prop['ui:placeholder'] || prop.placeholder || prop.description || 'Select an option...'} />;
    }
    const selected = options.findIndex(option => option === value);
    return <select value={selected < 0 ? '' : String(selected)} className={className} data-field-key={fieldKey}
        onChange={event => {
            const index = event.target.value;
            if (index === '') onChange(fieldKey, undefined);
            else if (/^(0|[1-9]\d*)$/.test(index) && Number(index) < options.length) onChange(fieldKey, options[Number(index)]);
        }}>
        <option value="" className="bg-card">{prop.default !== undefined && prop.default !== null
            ? `Default (${typeof prop.default === 'boolean' ? prop.default ? 'Yes' : 'No' : prop.default})` : 'Not set'}</option>
        {options.map((option, index) => <option key={index} value={String(index)} className="bg-card">{optionLabels[index]}</option>)}
    </select>;
}

// ============================================================================
// Field Renderer (generation variant - simple inputs)
// ============================================================================

/**
 * Render a schema field for the generation variant (simple inputs, no drag-drop).
 * Returns the input element only - wrapping/layout is handled by caller.
 *
 * First checks the widget registry for custom ui:widget types, then falls back
 * to type-based rendering for standard types (enum, boolean, number, text).
 */
export function renderGenerationField({
    fieldKey,
    fieldSchema: prop,
    value,
    onChange,
    isLoading = false,
    config,
}: SchemaFieldRenderOptions): ReactElement | null {
    const inputClasses = generationInputClasses;

    // First, try the shared widget registry for any ui:widget types
    const widgetElement = renderSchemaWidget({
        fieldKey,
        fieldSchema: prop,
        value,
        onChange,
        isLoading,
        config,
    });
    if (widgetElement) {
        return widgetElement;
    }

    const choice = renderSchemaChoice({ fieldKey, fieldSchema: prop, value, onChange }, inputClasses);
    if (choice) return choice;
    prop = fieldValueSchema(prop);

    // Textarea (when explicitly requested via ui:widget but not in registry)
    if (prop['ui:widget'] === 'textarea') {
        return (
            <textarea
                value={value || ''}
                onChange={(e) => onChange(fieldKey, e.target.value)}
                placeholder={prop.placeholder || prop.description}
                rows={3}
                className={`${inputClasses} resize-none`}
            />
        );
    }

    // Number/integer input
    if (prop.type === 'number' || prop.type === 'integer') {
        return (
            <input
                type="number"
                value={value ?? ''}
                onChange={(e) => {
                    const newValue = e.target.value;
                    if (newValue === '') {
                        onChange(fieldKey, '');
                    } else {
                        onChange(fieldKey, numericFieldValue(newValue, prop.type));
                    }
                }}
                placeholder={prop.placeholder || prop.description}
                className={inputClasses}
            />
        );
    }

    // Default: text input
    return (
        <input
            type="text"
            value={value || ''}
            onChange={(e) => onChange(fieldKey, e.target.value)}
            placeholder={prop.placeholder || `Enter ${prop.title || fieldKey}...`}
            className={inputClasses}
        />
    );
}

// ============================================================================
// Schema Utilities
// ============================================================================

/**
 * Check if a node type uses operations (has anyOf/oneOf in its config schema).
 * Returns false for nodes like iteration that have a single config structure.
 */
export function nodeTypeUsesOperations(rootSchema: any): boolean {
    if (!rootSchema) return false;

    const configSchema = rootSchema?.properties?.config || rootSchema;

    const resolveRef = (ref: string): any => {
        const path = ref.replace('#/$defs/', '');
        return rootSchema?.$defs?.[path] || rootSchema?.definitions?.[path];
    };

    const resolvedSchema = configSchema?.$ref ? resolveRef(configSchema.$ref) : configSchema;
    if (!resolvedSchema) return false;

    const options = resolvedSchema?.oneOf || resolvedSchema?.anyOf || [];
    return options.length > 0;
}

// ============================================================================
// Field Type Detection Utilities
// ============================================================================

/** Check if a field should be rendered with dynamic options dropdown */
export function hasDynamicOptions(fieldSchema: any): boolean {
    return !!fieldSchema?.['x-dynamic-options'];
}

/** Check if a field is a webhook field */
export function isWebhookField(fieldSchema: any): boolean {
    return fieldSchema?.['ui:widget'] === 'webhook';
}

/** Check if a field is readonly */
export function isReadonlyField(fieldSchema: any): boolean {
    return fieldSchema?.['ui:widget'] === 'readonly';
}

/** Check if a field has ui:loadValue (needs auto-loading) */
export function hasLoadValue(fieldSchema: any): boolean {
    return fieldSchema?.['ui:loadValue'] === true;
}

/** Check if a field is copyable */
export function isCopyableField(fieldSchema: any): boolean {
    return fieldSchema?.['ui:copyable'] === true;
}

/** Get display-friendly field label */
export function getFieldLabel(fieldKey: string, fieldSchema: any): string {
    return fieldSchema?.title || fieldKey;
}

/** Get field description */
export function getFieldDescription(fieldSchema: any): string | undefined {
    return fieldSchema?.description;
}
