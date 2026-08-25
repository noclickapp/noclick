// FormFieldsEditor - Widget for defining form input fields that users can submit.
// Each field has a label (auto-converted to identifier), type, description, required flag, and options.
// These fields define the schema for data that can be passed to workflow execution.

import { useEffect, useRef, useMemo } from 'react';
import { Plus, Trash2, X, ChevronDown } from 'lucide-react';
import { SearchableEnumField } from './SearchableEnumField';
import { DroppableTextField } from './DroppableTextField';
import { getServiceCredentialOptions, getServiceForCredentialType } from '~/utils/credentialTypes';

interface FormField {
    name: string;
    type: 'string' | 'number' | 'boolean' | 'object' | 'list' | 'select' | 'schedule' | 'file' | 'credential';
    label: string;
    description: string;
    required: boolean;
    options?: string[] | null;
    credential_type?: string | null;
    /** Accept filter for `file` fields (e.g. "image/*", ".pdf"). Empty = any. */
    accept?: string | null;
}

interface FormFieldsEditorProps {
    value: FormField[];
    onChange: (fields: FormField[]) => void;
    fieldKey: string;
}

const FIELD_TYPES = [
    { value: 'string', label: 'Text' },
    { value: 'number', label: 'Number' },
    { value: 'boolean', label: 'Boolean' },
    { value: 'select', label: 'Dropdown' },
    { value: 'schedule', label: 'Schedule' },
    { value: 'list', label: 'List' },
    { value: 'file', label: 'File Upload' },
    { value: 'credential', label: 'Credential' },
] as const;

// Convert label to valid identifier: "Email Address" → "email_address"
// Strips {{reference}} syntax before converting so references don't pollute the identifier.
const labelToIdentifier = (label: string): string => {
    let id = label
        .replace(/\{\{[^}]*\}\}/g, '')  // strip {{references}}
        .toLowerCase()
        .trim()
        .replace(/\s+/g, '_')           // spaces → underscores
        .replace(/[^a-z0-9_]/g, '')     // remove invalid chars
        .replace(/_+/g, '_')            // collapse multiple underscores
        .replace(/^_+|_+$/g, '');       // trim underscores

    // Ensure starts with letter or underscore (not number)
    if (id && /^[0-9]/.test(id)) {
        id = '_' + id;
    }

    return id || 'field';
};

// Parse form fields, handling various formats from workflow conversion:
// - Already an array: use as-is
// - JSON string: parse it
// - Invalid: return empty array
function parseFormFields(value: unknown): FormField[] {
    if (Array.isArray(value)) {
        return value;
    }
    if (typeof value === 'string' && value.trim()) {
        try {
            const parsed = JSON.parse(value);
            if (Array.isArray(parsed)) {
                return parsed;
            }
        } catch {
            // Failed to parse, return empty array
        }
    }
    return [];
}

// Ensure all fields have valid names (fix legacy data with empty names)
const ensureValidNames = (fields: FormField[]): FormField[] => {
    const usedNames = new Set<string>();
    return fields.map((field, index) => {
        let name = field.name;

        // If name is empty, generate from label or use default
        if (!name || name.trim() === '') {
            name = field.label ? labelToIdentifier(field.label) : `field_${index + 1}`;
        }

        // Ensure uniqueness
        let finalName = name;
        let counter = 1;
        while (usedNames.has(finalName)) {
            finalName = `${name}_${counter}`;
            counter++;
        }
        usedNames.add(finalName);

        return { ...field, name: finalName };
    });
};

export function FormFieldsEditor({ value, onChange, fieldKey }: FormFieldsEditorProps) {
    const rawFields = parseFormFields(value);
    const hasFixedRef = useRef(false);
    const serviceOptions = useMemo(() => getServiceCredentialOptions(), []);
    const serviceValues = useMemo(() => serviceOptions.map(o => o.value), [serviceOptions]);
    const serviceLabels = useMemo(() => serviceOptions.map(o => o.label), [serviceOptions]);

    // Fix legacy data with empty names on first load
    useEffect(() => {
        if (hasFixedRef.current || rawFields.length === 0) return;

        const fixedFields = ensureValidNames(rawFields);
        const needsFix = rawFields.some((f, i) => f.name !== fixedFields[i].name);

        if (needsFix) {
            hasFixedRef.current = true;
            onChange(fixedFields);
        }
    }, [rawFields, onChange]);

    // Always work with valid names for display
    const fields = ensureValidNames(rawFields);

    const addField = () => {
        // Generate a unique label like "Field 1", "Field 2", etc.
        let counter = 1;
        const existingNames = new Set(fields.map(f => f.name));
        while (existingNames.has(`field_${counter}`)) {
            counter++;
        }
        onChange([...fields, {
            name: `field_${counter}`,
            type: 'string',
            label: `Field ${counter}`,
            description: '',
            required: false,
            options: null
        }]);
    };

    const removeField = (index: number) => {
        onChange(fields.filter((_, i) => i !== index));
    };

    const updateField = (index: number, updates: Partial<FormField>) => {
        const newFields = [...fields];
        newFields[index] = { ...newFields[index], ...updates };

        // Auto-generate name from label
        if (updates.label !== undefined) {
            newFields[index].name = labelToIdentifier(updates.label);
        }

        // If changing to select type and no options exist, initialize with empty array
        if (updates.type === 'select' && !newFields[index].options) {
            newFields[index].options = [];
        }
        // If changing away from select type, clear options
        if (updates.type && updates.type !== 'select') {
            newFields[index].options = null;
        }
        // If changing to credential type, initialize credential_type
        if (updates.type === 'credential' && !newFields[index].credential_type) {
            newFields[index].credential_type = '';
        }
        // If changing away from credential type, clear credential fields
        if (updates.type && updates.type !== 'credential') {
            newFields[index].credential_type = null;
        }

        onChange(newFields);
    };

    const addOption = (fieldIndex: number) => {
        const field = fields[fieldIndex];
        const currentOptions = field.options || [];
        updateField(fieldIndex, {
            options: [...currentOptions, `Option ${currentOptions.length + 1}`]
        });
    };

    const removeOption = (fieldIndex: number, optionIndex: number) => {
        const field = fields[fieldIndex];
        const currentOptions = field.options || [];
        updateField(fieldIndex, {
            options: currentOptions.filter((_, i) => i !== optionIndex)
        });
    };

    const updateOption = (fieldIndex: number, optionIndex: number, value: string) => {
        const field = fields[fieldIndex];
        const currentOptions = [...(field.options || [])];
        currentOptions[optionIndex] = value;
        updateField(fieldIndex, { options: currentOptions });
    };

    return (
        <div className="space-y-2">
            {fields.map((field, index) => {
                const isDuplicate = fields.filter(f => f.name === field.name && field.name !== '').length > 1;
                const isSelectType = field.type === 'select';

                return (
                    <div key={index} className="p-2.5 rounded-lg border border-border dark:border-white/[0.05] bg-foreground/[0.02] space-y-2">
                        {/* Row 1: Label, Type, Required, Delete */}
                        <div className="flex items-center gap-2">
                            {/* Label input (name is auto-derived) */}
                            <div className="flex-1">
                                <DroppableTextField
                                    fieldKey={`${fieldKey}-label-${index}`}
                                    value={field.label}
                                    onChange={(newValue) => updateField(index, { label: newValue })}
                                    placeholder="Field Label (e.g., 'Email Address')"
                                    className={`text-xs py-1.5 ${isDuplicate ? '!border-red-500/50' : ''}`}
                                />
                            </div>

                            {/* Type dropdown */}
                            <div className="relative">
                                <select
                                    value={field.type}
                                    onChange={(e) => updateField(index, { type: e.target.value as FormField['type'] })}
                                    className="appearance-none cursor-pointer pl-2 pr-7 py-1.5 text-xs bg-foreground/[0.02] border border-border dark:border-white/[0.05] rounded text-foreground/80 focus:outline-none focus:border-border dark:focus:border-white/[0.15] transition-colors"
                                >
                                    {FIELD_TYPES.map(t => (
                                        <option key={t.value} value={t.value} className="bg-card">
                                            {t.label}
                                        </option>
                                    ))}
                                </select>
                                <ChevronDown className="absolute right-1.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground dark:text-zinc-500 pointer-events-none" />
                            </div>

                            {/* Required toggle */}
                            <button
                                type="button"
                                onClick={() => updateField(index, { required: !field.required })}
                                className={`px-2 py-1 text-[10px] font-medium rounded transition-colors ${
                                    field.required
                                        ? 'bg-orange-500/20 text-orange-600 dark:text-orange-400 border border-orange-500/30'
                                        : 'bg-secondary dark:bg-zinc-700/30 text-muted-foreground dark:text-zinc-500 border border-muted-foreground/40 dark:border-zinc-600/30 hover:text-muted-foreground'
                                }`}
                                title={field.required ? 'Click to make optional' : 'Click to make required'}
                            >
                                {field.required ? 'Required' : 'Optional'}
                            </button>

                            {/* Remove button */}
                            <button
                                type="button"
                                onClick={() => removeField(index)}
                                className="p-1.5 text-muted-foreground dark:text-zinc-500 hover:text-red-400 hover:bg-red-500/10 rounded transition-colors"
                                title="Remove field"
                            >
                                <Trash2 className="w-3.5 h-3.5" />
                            </button>
                        </div>

                        {/* Auto-generated identifier hint */}
                        {field.name && (
                            <div className="text-[10px] text-muted-foreground/70 dark:text-zinc-600 font-mono pl-0.5">
                                → {`{{${field.name}}}`}
                                {isDuplicate && <span className="text-red-500 ml-2">(duplicate)</span>}
                            </div>
                        )}

                        {/* Description */}
                        <DroppableTextField
                            fieldKey={`${fieldKey}-desc-${index}`}
                            value={field.description}
                            onChange={(newValue) => updateField(index, { description: newValue })}
                            placeholder="Help text (optional)"
                            className="text-xs py-1.5 text-muted-foreground"
                        />

                        {/* Credential service selector */}
                        {field.type === 'credential' && (
                            <div className="pt-1 space-y-1.5">
                                <div className="text-[10px] text-muted-foreground dark:text-zinc-500 uppercase tracking-wider">
                                    Service
                                </div>
                                <SearchableEnumField
                                    fieldKey={`form-field-${index}-credential-service`}
                                    value={getServiceForCredentialType(field.credential_type || '')?.value || ''}
                                    enumValues={serviceValues}
                                    enumLabels={serviceLabels}
                                    onChange={(_key, nodeType) => {
                                        const service = serviceOptions.find(o => o.value === nodeType);
                                        if (service) {
                                            updateField(index, {
                                                credential_type: service.primaryCredentialType,
                                            });
                                        }
                                    }}
                                    placeholder="Search services..."
                                />
                                {!field.credential_type && (
                                    <p className="text-[10px] text-amber-500/80">
                                        Select a service to configure credential collection
                                    </p>
                                )}
                            </div>
                        )}

                        {/* Options editor for select type */}
                        {isSelectType && (
                            <div className="pt-1 space-y-1.5">
                                <div className="text-[10px] text-muted-foreground dark:text-zinc-500 uppercase tracking-wider">
                                    Dropdown Options
                                </div>

                                {/* Existing options */}
                                {(field.options || []).map((option, optionIndex) => (
                                    <div key={optionIndex} className="flex items-center gap-1.5">
                                        <input
                                            type="text"
                                            value={option}
                                            onChange={(e) => updateOption(index, optionIndex, e.target.value)}
                                            placeholder={`Option ${optionIndex + 1}`}
                                            className="flex-1 px-2 py-1 text-xs bg-foreground/[0.02] border border-border dark:border-white/[0.05] rounded text-foreground/80 placeholder:text-[hsl(var(--placeholder))] focus:outline-none focus:border-border dark:focus:border-white/[0.15] transition-colors"
                                        />
                                        <button
                                            type="button"
                                            onClick={() => removeOption(index, optionIndex)}
                                            className="p-1 text-muted-foreground dark:text-zinc-500 hover:text-red-400 hover:bg-red-500/10 rounded transition-colors"
                                            title="Remove option"
                                        >
                                            <X className="w-3 h-3" />
                                        </button>
                                    </div>
                                ))}

                                {/* Add option button */}
                                <button
                                    type="button"
                                    onClick={() => addOption(index)}
                                    className="flex items-center gap-1 px-2 py-1 text-[10px] text-muted-foreground dark:text-zinc-500 hover:text-muted-foreground hover:bg-foreground/[0.03] rounded transition-colors border border-dashed border-border/50 dark:border-zinc-700/50 hover:border-border dark:hover:border-zinc-600"
                                >
                                    <Plus className="w-3 h-3" />
                                    <span>Add Option</span>
                                </button>

                                {/* Warning if no options */}
                                {(!field.options || field.options.length === 0) && (
                                    <p className="text-[10px] text-amber-500/80">
                                        Add at least one option for the dropdown
                                    </p>
                                )}
                            </div>
                        )}
                    </div>
                );
            })}

            {/* Add field button */}
            <button
                type="button"
                onClick={addField}
                className="flex items-center gap-1.5 px-2 py-1.5 text-xs text-muted-foreground hover:text-foreground/80 hover:bg-foreground/[0.04] rounded transition-colors border border-dashed border-border dark:border-zinc-700 hover:border-border dark:hover:border-zinc-600 w-full justify-center"
            >
                <Plus className="w-3.5 h-3.5" />
                <span>Add Field</span>
            </button>

            {/* Help text */}
            {fields.length === 0 && (
                <p className="text-[10px] text-muted-foreground/70 dark:text-zinc-600 mt-1 text-center">
                    Define the input fields for this form. Apps can pass data through these fields when executing the workflow.
                </p>
            )}
        </div>
    );
}
