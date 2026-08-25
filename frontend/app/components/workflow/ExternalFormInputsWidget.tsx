// Config widget for the Submit External Form node's `inputs` field.
// Reads the sibling `workflow` + `form` config values, loads the selected form's
// field definitions from the backend (load-options field_name "form_fields"),
// and renders one fillable, reference-droppable input per field. Filled values are
// persisted as a { fieldName: value } object so execute() can submit them.

import { useCallback, useEffect, useRef, useState } from 'react';
import { sendEventAsync } from '~/lib/socket-sender';
import { WorkflowNodeLoadOptionsRequest } from '~/types/socket-events.generated';
import { DroppableTextField } from './DroppableTextField';
import { SearchableEnumField } from './SearchableEnumField';
import type { WidgetRenderProps } from './schemaWidgetRegistry';

interface FormFieldOption {
    value: string;
    label: string;
}

interface FormFieldMeta {
    name: string;
    label: string;
    type: string;
    required: boolean;
    description: string;
    options: FormFieldOption[];
}

function normalizeOptions(raw: unknown): FormFieldOption[] {
    if (!Array.isArray(raw)) return [];
    return raw.map((opt) => {
        if (opt && typeof opt === 'object') {
            const o = opt as Record<string, unknown>;
            const value = String(o.value ?? o.label ?? '');
            return { value, label: String(o.label ?? value) };
        }
        const s = String(opt);
        return { value: s, label: s };
    });
}

function toFields(options: Array<{ value: string; label: string; metadata?: Record<string, unknown> | null }>): FormFieldMeta[] {
    return options.map((opt) => {
        const meta = opt.metadata || {};
        return {
            name: opt.value,
            label: opt.label || opt.value,
            type: String(meta.type ?? 'string'),
            required: Boolean(meta.required),
            description: String(meta.description ?? ''),
            options: normalizeOptions(meta.options),
        };
    });
}

export function ExternalFormInputsWidget({ fieldKey, value, onChange, config, nodeType }: WidgetRenderProps) {
    const values = (value && typeof value === 'object' ? value : {}) as Record<string, unknown>;

    const workflowId = (config?.workflow as string) || '';
    const formId = (config?.form as string) || '';

    const [fields, setFields] = useState<FormFieldMeta[]>([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const loadFields = useCallback(async () => {
        if (!workflowId || !formId) {
            setFields([]);
            return;
        }
        setLoading(true);
        setError(null);
        try {
            const resp = await sendEventAsync(
                WorkflowNodeLoadOptionsRequest.create({
                    node_type: nodeType || 'automation-submit-external-form',
                    field_name: 'form_fields',
                    credential_id: '',
                    context: { workflow: workflowId, form: formId },
                }),
            );
            if (resp && resp.success) {
                setFields(toFields(resp.options || []));
            } else {
                setFields([]);
                setError(resp?.message || 'Could not load the form fields');
            }
        } catch (err) {
            setFields([]);
            setError(err instanceof Error ? err.message : 'Could not load the form fields');
        } finally {
            setLoading(false);
        }
    }, [workflowId, formId, nodeType]);

    // Load on mount and whenever the selected workflow/form changes.
    const prevKey = useRef<string>('');
    useEffect(() => {
        const key = `${workflowId}::${formId}`;
        if (prevKey.current === key) return;
        prevKey.current = key;
        loadFields();
    }, [workflowId, formId, loadFields]);

    const setFieldValue = (name: string, next: string) => {
        onChange(fieldKey, { ...values, [name]: next });
    };

    if (!workflowId || !formId) {
        return <div className="text-xs text-muted-foreground/70 dark:text-white/40 py-1">Select a workflow and form above to fill its fields.</div>;
    }
    if (loading) {
        return <div className="text-xs text-muted-foreground/70 dark:text-white/40 py-1">Loading form fields…</div>;
    }
    if (error) {
        return <div className="text-xs text-red-600 dark:text-red-400 py-1">{error}</div>;
    }
    if (fields.length === 0) {
        return <div className="text-xs text-muted-foreground/70 dark:text-white/40 py-1">This form has no fields to fill.</div>;
    }

    return (
        <div className="space-y-3">
            {fields.map((field) => {
                const current = values[field.name];
                const currentStr = current == null ? '' : String(current);
                const inputKey = `${fieldKey}_${field.name}`;
                return (
                    <div key={field.name} className="space-y-1">
                        <label className="block text-xs font-medium text-muted-foreground dark:text-white/60">
                            {field.label}
                            {field.required && <span className="text-red-600 dark:text-red-400 ml-1">*</span>}
                        </label>
                        {field.type === 'select' && field.options.length > 0 ? (
                            <SearchableEnumField
                                fieldKey={inputKey}
                                value={currentStr}
                                enumValues={field.options.map((o) => o.value)}
                                enumLabels={field.options.map((o) => o.label)}
                                onChange={(_key, val) => setFieldValue(field.name, val)}
                                placeholder={`Select ${field.label}…`}
                            />
                        ) : (
                            <DroppableTextField
                                fieldKey={inputKey}
                                value={currentStr}
                                onChange={(val) => setFieldValue(field.name, val)}
                                placeholder={field.description || `Enter ${field.label} or drop a {{reference}}`}
                            />
                        )}
                    </div>
                );
            })}
        </div>
    );
}
