// VariableAssignmentsEditor - Widget for defining variable assignments in set-variable nodes.
// Each assignment has a variable name and a value (supports {{references}} via drag-and-drop).
// Shows a hint below each name indicating the resulting {{vars.name}} reference path.

import { useEffect, useRef } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import { DroppableTextField } from './DroppableTextField';
import { decodeLegacyHtmlEntities } from './legacyConfigParsing';

interface VariableAssignment {
    variable_name: string;
    value: string;
}

interface VariableAssignmentsEditorProps {
    value: VariableAssignment[];
    onChange: (assignments: VariableAssignment[]) => void;
    fieldKey: string;
}

function parseAssignments(value: unknown): VariableAssignment[] {
    let arr: any[] = [];
    if (Array.isArray(value)) {
        arr = value;
    } else if (typeof value === 'string' && value.trim()) {
        try {
            const decoded = decodeLegacyHtmlEntities(value);
            const parsed = JSON.parse(decoded);
            if (Array.isArray(parsed)) arr = parsed;
        } catch { /* return empty */ }
    }
    return arr.map(a => ({
        variable_name: a?.variable_name ?? '',
        value: a?.value ?? '',
    }));
}

export function VariableAssignmentsEditor({ value, onChange, fieldKey }: VariableAssignmentsEditorProps) {
    const assignments = parseAssignments(value);

    // Propagate sanitized data back once if the raw value contained null fields
    const sanitizedRef = useRef(false);
    useEffect(() => {
        if (sanitizedRef.current) return;
        const raw = Array.isArray(value) ? value : [];
        const hasNulls = raw.some((a: any) => a?.value == null || a?.variable_name == null);
        if (hasNulls) {
            sanitizedRef.current = true;
            onChange(assignments);
        }
    }, [value]); // eslint-disable-line react-hooks/exhaustive-deps

    const addAssignment = () => {
        const existingNames = new Set(assignments.map(a => a.variable_name));
        let counter = 1;
        while (existingNames.has(`var_${counter}`)) counter++;
        onChange([...assignments, { variable_name: `var_${counter}`, value: '' }]);
    };

    const removeAssignment = (index: number) => {
        onChange(assignments.filter((_, i) => i !== index));
    };

    const updateAssignment = (index: number, field: 'variable_name' | 'value', newValue: string) => {
        const updated = [...assignments];
        updated[index] = { ...updated[index], [field]: newValue };
        onChange(updated);
    };

    return (
        <div className="space-y-2">
            {assignments.map((assignment, index) => {
                const isDuplicate = assignments.filter(a => a.variable_name === assignment.variable_name && assignment.variable_name !== '').length > 1;

                return (
                    <div key={index} className="p-2.5 rounded-lg border border-border dark:border-white/[0.05] bg-foreground/[0.02] space-y-1.5">
                        <div className="flex items-start gap-2">
                            {/* Variable name */}
                            <div className="flex-1 min-w-0">
                                <DroppableTextField
                                    fieldKey={`${fieldKey}-name-${index}`}
                                    value={assignment.variable_name}
                                    onChange={(v) => updateAssignment(index, 'variable_name', v)}
                                    placeholder="variable_name"
                                    className={`text-xs py-1.5 font-mono ${isDuplicate ? '!border-red-500/50' : ''}`}
                                />
                            </div>

                            <span className="text-muted-foreground dark:text-zinc-500 text-xs pt-1.5">=</span>

                            {/* Value (droppable) */}
                            <div className="flex-1 min-w-0">
                                <DroppableTextField
                                    fieldKey={`${fieldKey}-val-${index}`}
                                    value={assignment.value}
                                    onChange={(v) => updateAssignment(index, 'value', v)}
                                    placeholder="{{node.field}} or value"
                                    className="text-xs py-1.5"
                                />
                            </div>

                            {/* Remove */}
                            <button
                                type="button"
                                onClick={() => removeAssignment(index)}
                                className="flex-shrink-0 p-1.5 text-muted-foreground dark:text-zinc-500 hover:text-red-400 hover:bg-red-500/10 rounded transition-colors"
                                title="Remove variable"
                            >
                                <Trash2 className="w-3.5 h-3.5" />
                            </button>
                        </div>

                        {/* Reference hint */}
                        {assignment.variable_name && (
                            <div className="text-[10px] text-muted-foreground/70 dark:text-zinc-600 font-mono pl-0.5">
                                → {`{{vars.${assignment.variable_name}}}`}
                                {isDuplicate && <span className="text-red-500 ml-2">(duplicate)</span>}
                            </div>
                        )}
                    </div>
                );
            })}

            {/* Add button */}
            <button
                type="button"
                onClick={addAssignment}
                className="flex items-center gap-1.5 px-2 py-1.5 text-xs text-muted-foreground hover:text-foreground/80 hover:bg-foreground/[0.04] rounded transition-colors border border-dashed border-border dark:border-zinc-700 hover:border-border dark:hover:border-zinc-600 w-full justify-center"
            >
                <Plus className="w-3.5 h-3.5" />
                <span>Add Variable</span>
            </button>

            {assignments.length === 0 && (
                <p className="text-[10px] text-muted-foreground/70 dark:text-zinc-600 mt-1 text-center">
                    Define variables to store. Values are accessible as {'{{vars.name}}'} in the workflow.
                </p>
            )}
        </div>
    );
}
