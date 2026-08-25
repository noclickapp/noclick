/**
 * schemaFieldRenderer - Shared field rendering logic for JSON Schema-based config forms.
 * Used by both NodeConfig (workflow editor) and SchemaConfigForm (workflow generation).
 *
 * Provides two variants:
 * - 'editor': Full-featured with DroppableTextField for drag-drop support
 * - 'generation': Simplified for workflow generation setup panel
 */

import type { ReactElement } from 'react';
import { renderSchemaWidget, hasRegisteredWidget, type WidgetRenderProps } from './schemaWidgetRegistry';

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

    // Enum (select dropdown)
    if (prop.enum) {
        return (
            <select
                value={value || ''}
                onChange={(e) => onChange(fieldKey, e.target.value)}
                className={inputClasses}
            >
                <option value="" className="bg-card">Select...</option>
                {prop.enum.map((opt: string) => (
                    <option key={opt} value={opt} className="bg-card">
                        {(prop.enumLabels || {})[opt] || opt}
                    </option>
                ))}
            </select>
        );
    }

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

    // Boolean checkbox
    if (prop.type === 'boolean') {
        return (
            <label className="flex items-center gap-2 cursor-pointer">
                <input
                    type="checkbox"
                    checked={!!value}
                    onChange={(e) => onChange(fieldKey, e.target.checked)}
                    className="w-4 h-4 rounded border-foreground/20 bg-foreground/5 text-emerald-500 focus:ring-emerald-500/20"
                />
                <span className="text-sm text-muted-foreground">{prop.description || 'Enable'}</span>
            </label>
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
                        const num = prop.type === 'integer' ? parseInt(newValue, 10) : parseFloat(newValue);
                        onChange(fieldKey, isNaN(num) ? newValue : num);
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
