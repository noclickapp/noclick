// Interface form node for rendering a configurable multi-field form in the workflow canvas.
// Includes a display strategy so the output panel shows each form field as a draggable
// variable (e.g. {{nodeId.fieldName}}) even before execution, derived from node config.

import { NodeProps } from '@xyflow/react';
import { ClipboardList, GripVertical } from 'lucide-react';
import { useDraggable } from '@dnd-kit/core';
import InterfaceNode from './InterfaceNode';
import type {
    NodeDefinition,
    NodeDisplayStrategy,
    OutputPanelContentProps,
    JsonValue,
    JsonObject,
    ReferenceSuggestion,
} from '../types';

const DIMENSIONS = { width: 500, height: 450, iconSize: 48 };

// ============================================================================
// Output Shape Helpers
// ============================================================================

interface FormFieldSchema {
    name: string;
    type: string;
    label: string;
    description?: string;
    required?: boolean;
    options?: string[] | null;
}

function asFormOutput(output: JsonValue): { fields: FormFieldSchema[]; values: JsonObject } | null {
    if (output === null || typeof output !== 'object' || Array.isArray(output)) return null;
    const obj = output as JsonObject;
    if (!Array.isArray(obj.fields)) return null;
    return { fields: obj.fields as unknown as FormFieldSchema[], values: obj };
}

function fieldTypeToValueType(type: string): ReferenceSuggestion['valueType'] {
    switch (type) {
        case 'number': return 'number';
        case 'boolean': return 'boolean';
        case 'list': case 'array': return 'array';
        case 'object': return 'object';
        default: return 'string';
    }
}

function fieldTypeLabel(type: string): string {
    switch (type) {
        case 'string': return 'text';
        case 'number': return 'number';
        case 'boolean': return 'boolean';
        case 'select': return 'select';
        case 'schedule': return 'schedule';
        case 'credential': return 'credential';
        case 'list': return 'list';
        default: return type;
    }
}

function fieldTypeColor(type: string): string {
    switch (type) {
        case 'string': return 'text-emerald-600 dark:text-emerald-400 bg-emerald-400/10';
        case 'number': return 'text-blue-600 dark:text-blue-400 bg-blue-400/10';
        case 'boolean': return 'text-amber-600 dark:text-amber-400 bg-amber-400/10';
        case 'select': return 'text-purple-600 dark:text-purple-400 bg-purple-400/10';
        case 'schedule': return 'text-cyan-600 dark:text-cyan-400 bg-cyan-400/10';
        case 'credential': return 'text-orange-600 dark:text-orange-400 bg-orange-400/10';
        case 'list': return 'text-cyan-600 dark:text-cyan-400 bg-cyan-400/10';
        default: return 'text-muted-foreground bg-zinc-400/10';
    }
}

function formatPreview(val: JsonValue): string {
    if (val === undefined || val === null) return '—';
    if (typeof val === 'string') return val.length > 40 ? `"${val.slice(0, 40)}..."` : `"${val}"`;
    if (typeof val === 'number' || typeof val === 'boolean') return String(val);
    if (Array.isArray(val)) return `[${val.length} items]`;
    if (typeof val === 'object') return `{${Object.keys(val as JsonObject).length} keys}`;
    return String(val);
}

/** Parse form fields from node data, handling both array and JSON string formats. */
function parseFieldsFromNodeData(nodeData: Record<string, unknown>): FormFieldSchema[] {
    const raw = (nodeData.config as Record<string, unknown> | undefined)?.fields;
    if (Array.isArray(raw)) return raw as unknown as FormFieldSchema[];
    if (typeof raw === 'string') {
        try {
            const parsed = JSON.parse(raw);
            if (Array.isArray(parsed)) return parsed;
        } catch { /* ignore */ }
    }
    return [];
}

/** The node's persisted value store (config.values), for pre-run previews. */
function parseValuesFromNodeData(nodeData: Record<string, unknown>): JsonObject {
    let raw = (nodeData.config as Record<string, unknown> | undefined)?.values;
    if (typeof raw === 'string') {
        try {
            raw = JSON.parse(raw);
        } catch { /* ignore */ }
    }
    return raw && typeof raw === 'object' && !Array.isArray(raw) ? (raw as JsonObject) : {};
}

// ============================================================================
// Display Strategy
// ============================================================================

function buildSuggestions(output: JsonValue, nodeId: string): ReferenceSuggestion[] {
    const parsed = asFormOutput(output);
    if (!parsed) return [];

    return parsed.fields.map(field => ({
        reference: `${nodeId}.${field.name}`,
        label: field.label || field.name,
        nodeId,
        path: field.name,
        valueType: fieldTypeToValueType(field.type),
        value: parsed.values[field.name] ?? `<${fieldTypeLabel(field.type)}>`,
        depth: 0,
    }));
}

function buildSuggestionsFromConfig(nodeData: Record<string, unknown>, nodeId: string): ReferenceSuggestion[] {
    const fields = parseFieldsFromNodeData(nodeData);
    const stored = parseValuesFromNodeData(nodeData);
    return fields.map(field => ({
        reference: `${nodeId}.${field.name}`,
        label: field.label || field.name,
        nodeId,
        path: field.name,
        valueType: fieldTypeToValueType(field.type),
        // Persisted store values preview before any run
        value: stored[field.name] ?? `<${fieldTypeLabel(field.type)}>`,
        depth: 0,
    }));
}

function validateReference(output: JsonValue, path: string): { valid: boolean; error?: string } {
    const parsed = asFormOutput(output);
    if (!parsed) return { valid: false, error: 'No form output available' };
    if (['type', 'fields', 'status', 'timestamp', 'values'].includes(path)) return { valid: true };
    // Legacy config-form references: {{nodeId.values.fieldName}}
    const fieldName = path.startsWith('values.') ? path.slice('values.'.length) : path;
    if (parsed.fields.some(f => f.name === fieldName)) return { valid: true };
    const available = parsed.fields.map(f => f.name).join(', ');
    return { valid: false, error: `Field "${fieldName}" not defined. Available: ${available}` };
}

// ============================================================================
// Variable Row Component
// ============================================================================

const FormVariableRow = ({
    nodeId,
    field,
    value,
    draggable = true,
}: {
    nodeId: string;
    field: FormFieldSchema;
    value: JsonValue;
    draggable?: boolean;
}) => {
    const dragId = `form-var-${nodeId}-${field.name}`;
    const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
        id: dragId,
        data: {
            type: 'json-field-reference',
            nodeId,
            path: field.name,
            value,
            displayValue: formatPreview(value),
        },
        disabled: !draggable,
    });

    const hasValue = value !== undefined && value !== null && !(typeof value === 'string' && value.startsWith('<') && value.endsWith('>'));

    return (
        <div
            ref={draggable ? setNodeRef : undefined}
            {...(draggable ? attributes : {})}
            {...(draggable ? listeners : {})}
            className={`flex items-center gap-2 px-2.5 py-1.5 rounded-lg border transition-all ${
                draggable ? 'cursor-grab active:cursor-grabbing' : ''
            } ${
                isDragging
                    ? 'opacity-50 border-muted-foreground/50 dark:border-zinc-500/50 bg-zinc-500/10'
                    : 'border-border/50 dark:border-zinc-700/50 bg-muted/30 hover:border-muted-foreground/40 dark:hover:border-zinc-600/50 hover:bg-accent dark:hover:bg-zinc-800/50'
            }`}
        >
            {draggable && <GripVertical className="h-3 w-3 text-muted-foreground/70 dark:text-zinc-600 flex-shrink-0" />}
            <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                    <code className="text-xs text-foreground font-medium">{field.label || field.name}</code>
                    <span className={`text-[9px] px-1.5 py-0.5 rounded ${fieldTypeColor(field.type)}`}>
                        {fieldTypeLabel(field.type)}
                    </span>
                    {field.required && (
                        <span className="text-[9px] px-1.5 py-0.5 rounded text-orange-600 dark:text-orange-400 bg-orange-400/10">
                            required
                        </span>
                    )}
                </div>
                <div className={`text-[10px] truncate font-mono mt-0.5 ${hasValue ? 'text-muted-foreground dark:text-zinc-500' : 'text-muted-foreground/70 dark:text-zinc-600 italic'}`}>
                    {hasValue ? formatPreview(value) : (field.description || `<${fieldTypeLabel(field.type)}>`)}
                </div>
            </div>
        </div>
    );
};

// ============================================================================
// Output Panel Content
// ============================================================================

const FormOutputPanelContent = ({ nodeId, output, draggable = true, nodeData }: OutputPanelContentProps) => {
    const parsed = asFormOutput(output);

    // Before execution: derive fields from node config, previewing the
    // persisted value store where it has entries
    if (!parsed) {
        const fields = nodeData ? parseFieldsFromNodeData(nodeData) : [];
        const stored = nodeData ? parseValuesFromNodeData(nodeData) : {};

        if (fields.length > 0) {
            return (
                <div className="space-y-3">
                    <div className="space-y-1.5">
                        <div className="text-[10px] text-muted-foreground dark:text-zinc-500 uppercase tracking-wider">
                            Form Fields
                        </div>
                        <p className="text-[10px] text-muted-foreground/70 dark:text-zinc-600 mb-2">
                            Drag a field to reference its submitted value
                        </p>
                        {fields.map(field => (
                            <FormVariableRow
                                key={field.name}
                                nodeId={nodeId}
                                field={field}
                                value={stored[field.name] as JsonValue}
                                draggable={draggable}
                            />
                        ))}
                    </div>
                </div>
            );
        }

        return (
            <div className="text-xs text-muted-foreground dark:text-zinc-500 italic py-2">
                No form output available. Add fields in the node configuration.
            </div>
        );
    }

    // After execution: show fields with actual submitted values
    return (
        <div className="space-y-3">
            <div className="space-y-1.5">
                <div className="text-[10px] text-muted-foreground dark:text-zinc-500 uppercase tracking-wider">
                    Submitted Values
                </div>
                <p className="text-[10px] text-muted-foreground/70 dark:text-zinc-600 mb-2">
                    Drag a field to use its value in another node
                </p>
                {parsed.fields.map(field => (
                    <FormVariableRow
                        key={field.name}
                        nodeId={nodeId}
                        field={field}
                        value={parsed.values[field.name]}
                        draggable={draggable}
                    />
                ))}
            </div>

            {parsed.fields.length === 0 && (
                <div className="text-xs text-muted-foreground dark:text-zinc-500 italic py-2">
                    No fields defined. Add fields in the node configuration.
                </div>
            )}
        </div>
    );
};

// ============================================================================
// Display Strategy Export
// ============================================================================

export const formDisplayStrategy: NodeDisplayStrategy = {
    buildSuggestions,
    buildSuggestionsFromConfig,
    validateReference,
    OutputPanelContent: FormOutputPanelContent,
};

// ============================================================================
// Node Component
// ============================================================================

const InterfaceFormNodeComponent = (props: NodeProps) => {
    return <InterfaceNode {...props} Icon={ClipboardList} iconColor="text-foreground" />;
};

export const InterfaceFormNode: NodeDefinition = {
    type: 'interface-form',
    label: 'Form',
    description: 'Multi-field form with a public shareable link — submissions start a run',
    Icon: ClipboardList,
    // text-foreground like the other dedicated trigger nodes (white in dark mode)
    iconColor: 'text-foreground',
    dimensions: DIMENSIONS,
    component: InterfaceFormNodeComponent,
    displayStrategy: formDisplayStrategy,
};
