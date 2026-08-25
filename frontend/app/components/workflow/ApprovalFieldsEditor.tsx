// ApprovalFieldsEditor — Like FormFieldsEditor but each field also has a "Value" input
// that supports {{references}} for pre-filling the approval form at execution time.

import { useEffect, useRef } from 'react';
import { Plus, Trash2, X } from 'lucide-react';
import { DroppableTextField } from './DroppableTextField';

interface ApprovalField {
    name: string;
    type: 'string' | 'number' | 'boolean' | 'select';
    label: string;
    description: string;
    required: boolean;
    options?: string[] | null;
    value: string;
}

interface ApprovalFieldsEditorProps {
    value: ApprovalField[];
    onChange: (fields: ApprovalField[]) => void;
    fieldKey: string;
}

const FIELD_TYPES = [
    { value: 'string', label: 'Text' },
    { value: 'number', label: 'Number' },
    { value: 'boolean', label: 'Boolean' },
    { value: 'select', label: 'Dropdown' },
    { value: 'media', label: 'Media' },
] as const;

const labelToIdentifier = (label: string): string => {
    let id = label
        .replace(/\{\{[^}]*\}\}/g, '')
        .toLowerCase().trim()
        .replace(/\s+/g, '_')
        .replace(/[^a-z0-9_]/g, '')
        .replace(/_+/g, '_')
        .replace(/^_+|_+$/g, '');
    if (id && /^[0-9]/.test(id)) id = '_' + id;
    return id || 'field';
};

function parseFields(value: unknown): ApprovalField[] {
    if (Array.isArray(value)) return value;
    if (typeof value === 'string' && value.trim()) {
        try {
            const parsed = JSON.parse(value);
            if (Array.isArray(parsed)) return parsed;
        } catch { /* ignore */ }
    }
    return [];
}

const ensureValidNames = (fields: ApprovalField[]): ApprovalField[] => {
    const used = new Set<string>();
    return fields.map((field, i) => {
        let name = field.name || (field.label ? labelToIdentifier(field.label) : `field_${i + 1}`);
        let final = name;
        let c = 1;
        while (used.has(final)) { final = `${name}_${c++}`; }
        used.add(final);
        return { ...field, name: final };
    });
};

export function ApprovalFieldsEditor({ value, onChange, fieldKey }: ApprovalFieldsEditorProps) {
    const rawFields = parseFields(value);
    const hasFixedRef = useRef(false);

    useEffect(() => {
        if (hasFixedRef.current || rawFields.length === 0) return;
        const fixed = ensureValidNames(rawFields);
        if (rawFields.some((f, i) => f.name !== fixed[i].name)) {
            hasFixedRef.current = true;
            onChange(fixed);
        }
    }, [rawFields, onChange]);

    const fields = ensureValidNames(rawFields);

    const addField = () => {
        let c = 1;
        const names = new Set(fields.map(f => f.name));
        while (names.has(`field_${c}`)) c++;
        onChange([...fields, {
            name: `field_${c}`, type: 'string', label: `Field ${c}`,
            description: '', required: false, options: null, value: '',
        }]);
    };

    const removeField = (i: number) => onChange(fields.filter((_, idx) => idx !== i));

    const updateField = (i: number, updates: Partial<ApprovalField>) => {
        const next = [...fields];
        next[i] = { ...next[i], ...updates };
        if (updates.label !== undefined) next[i].name = labelToIdentifier(updates.label);
        if (updates.type === 'select' && !next[i].options) next[i].options = [];
        if (updates.type && updates.type !== 'select') next[i].options = null;
        onChange(next);
    };

    const addOption = (fi: number) => {
        const opts = fields[fi].options || [];
        updateField(fi, { options: [...opts, `Option ${opts.length + 1}`] });
    };
    const removeOption = (fi: number, oi: number) => {
        updateField(fi, { options: (fields[fi].options || []).filter((_, i) => i !== oi) });
    };
    const updateOption = (fi: number, oi: number, val: string) => {
        const opts = [...(fields[fi].options || [])];
        opts[oi] = val;
        updateField(fi, { options: opts });
    };

    return (
        <div className="space-y-2">
            {fields.map((field, index) => {
                const isDuplicate = fields.filter(f => f.name === field.name && field.name !== '').length > 1;
                return (
                    <div key={index} className="p-2.5 rounded-lg border border-border dark:border-white/[0.05] bg-foreground/[0.02] space-y-2">
                        {/* Row 1: Label, Type, Required, Delete */}
                        <div className="flex items-center gap-2">
                            <div className="flex-1">
                                <DroppableTextField
                                    fieldKey={`${fieldKey}-label-${index}`}
                                    value={field.label}
                                    onChange={(v) => updateField(index, { label: v })}
                                    placeholder="Field Label"
                                    className={`text-xs py-1.5 ${isDuplicate ? '!border-red-500/50' : ''}`}
                                />
                            </div>
                            <select
                                value={field.type}
                                onChange={(e) => updateField(index, { type: e.target.value as ApprovalField['type'] })}
                                className="px-2 py-1.5 text-xs bg-foreground/[0.02] border border-border dark:border-white/[0.05] rounded text-foreground/80 focus:outline-none focus:border-border dark:focus:border-white/[0.15] transition-colors"
                            >
                                {FIELD_TYPES.map(t => (
                                    <option key={t.value} value={t.value} className="bg-card">{t.label}</option>
                                ))}
                            </select>
                            <button
                                type="button"
                                onClick={() => updateField(index, { required: !field.required })}
                                className={`px-2 py-1 text-[10px] font-medium rounded transition-colors ${
                                    field.required
                                        ? 'bg-orange-500/20 text-orange-600 dark:text-orange-400 border border-orange-500/30'
                                        : 'bg-secondary dark:bg-zinc-700/30 text-muted-foreground dark:text-zinc-500 border border-muted-foreground/40 dark:border-zinc-600/30 hover:text-muted-foreground'
                                }`}
                            >
                                {field.required ? 'Required' : 'Optional'}
                            </button>
                            <button
                                type="button"
                                onClick={() => removeField(index)}
                                className="p-1.5 text-muted-foreground dark:text-zinc-500 hover:text-red-400 hover:bg-red-500/10 rounded transition-colors"
                            >
                                <Trash2 className="w-3.5 h-3.5" />
                            </button>
                        </div>

                        {/* Identifier hint */}
                        {field.name && (
                            <div className="text-[10px] text-muted-foreground/70 dark:text-zinc-600 font-mono pl-0.5">
                                → {`{{${field.name}}}`}
                                {isDuplicate && <span className="text-red-500 ml-2">(duplicate)</span>}
                            </div>
                        )}

                        {/* Value — the key differentiator from FormFieldsEditor */}
                        <DroppableTextField
                            fieldKey={`${fieldKey}-value-${index}`}
                            value={field.value}
                            onChange={(v) => updateField(index, { value: v })}
                            placeholder="Value (e.g. {{upstream_node.field}})"
                            className="text-xs py-1.5 !border-teal-500/20 focus-within:!border-teal-500/40"
                        />

                        {/* Description */}
                        <DroppableTextField
                            fieldKey={`${fieldKey}-desc-${index}`}
                            value={field.description}
                            onChange={(v) => updateField(index, { description: v })}
                            placeholder="Help text (optional)"
                            className="text-xs py-1.5 text-muted-foreground"
                        />

                        {/* Options for select type */}
                        {field.type === 'select' && (
                            <div className="pt-1 space-y-1.5">
                                <div className="text-[10px] text-muted-foreground dark:text-zinc-500 uppercase tracking-wider">Options</div>
                                {(field.options || []).map((opt, oi) => (
                                    <div key={oi} className="flex items-center gap-1.5">
                                        <input
                                            type="text" value={opt}
                                            onChange={(e) => updateOption(index, oi, e.target.value)}
                                            placeholder={`Option ${oi + 1}`}
                                            className="flex-1 px-2 py-1 text-xs bg-foreground/[0.02] border border-border dark:border-white/[0.05] rounded text-foreground/80 placeholder:text-[hsl(var(--placeholder))] focus:outline-none focus:border-border dark:focus:border-white/[0.15]"
                                        />
                                        <button type="button" onClick={() => removeOption(index, oi)}
                                            className="p-1 text-muted-foreground dark:text-zinc-500 hover:text-red-400 hover:bg-red-500/10 rounded">
                                            <X className="w-3 h-3" />
                                        </button>
                                    </div>
                                ))}
                                <button type="button" onClick={() => addOption(index)}
                                    className="flex items-center gap-1 px-2 py-1 text-[10px] text-muted-foreground dark:text-zinc-500 hover:text-muted-foreground hover:bg-foreground/[0.03] rounded border border-dashed border-border/50 dark:border-zinc-700/50 hover:border-border dark:hover:border-zinc-600">
                                    <Plus className="w-3 h-3" /><span>Add Option</span>
                                </button>
                            </div>
                        )}
                    </div>
                );
            })}

            <button type="button" onClick={addField}
                className="flex items-center gap-1.5 px-2 py-1.5 text-xs text-muted-foreground hover:text-foreground/80 hover:bg-foreground/[0.04] rounded border border-dashed border-border dark:border-zinc-700 hover:border-border dark:hover:border-zinc-600 w-full justify-center">
                <Plus className="w-3.5 h-3.5" /><span>Add Field</span>
            </button>

            {fields.length === 0 && (
                <p className="text-[10px] text-muted-foreground/70 dark:text-zinc-600 mt-1 text-center">
                    Define the fields approvers will review. Use references to pre-fill values from upstream nodes.
                </p>
            )}
        </div>
    );
}
