// FunctionInputsEditor - Widget for defining named function inputs with drag-drop values.
// Each input has a variable name (Python identifier) and a value (supports {{node.field}} references).
// Used by the serverless function node to map upstream node outputs to function parameters.

import { Plus, Trash2 } from 'lucide-react';
import { DroppableTextField } from './DroppableTextField';
import { decodeLegacyHtmlEntities } from './legacyConfigParsing';

interface FunctionInput {
    name: string;
    value: string;
}

interface FunctionInputsEditorProps {
    value: FunctionInput[];
    onChange: (inputs: FunctionInput[]) => void;
    fieldKey: string; // Base key for generating unique droppable IDs
}

// Validate Python identifier: starts with letter/underscore, followed by letters/digits/underscores
const isValidPythonIdentifier = (name: string): boolean => {
    return /^[a-zA-Z_][a-zA-Z0-9_]*$/.test(name);
};

// Parse function inputs, handling various formats:
// - Already an array: use as-is
// - JSON string: parse it
// - HTML-encoded JSON string: decode and parse
// - Invalid: return empty array
function parseInputs(value: unknown): FunctionInput[] {
    if (Array.isArray(value)) {
        return value;
    }
    if (typeof value === 'string' && value.trim()) {
        try {
            // Decode HTML entities (e.g., &quot; -> ")
            const decoded = decodeLegacyHtmlEntities(value);
            const parsed = JSON.parse(decoded);
            if (Array.isArray(parsed)) {
                return parsed;
            }
        } catch {
            // Failed to parse, return empty array
        }
    }
    return [];
}

export function FunctionInputsEditor({ value, onChange, fieldKey }: FunctionInputsEditorProps) {
    const inputs = parseInputs(value);

    const addInput = () => {
        // Generate a default name like input_1, input_2, etc.
        const existingNames = new Set(inputs.map(i => i.name));
        let counter = 1;
        while (existingNames.has(`input_${counter}`)) {
            counter++;
        }
        onChange([...inputs, { name: `input_${counter}`, value: '' }]);
    };

    const removeInput = (index: number) => {
        const newInputs = inputs.filter((_, i) => i !== index);
        onChange(newInputs);
    };

    const updateInput = (index: number, field: 'name' | 'value', newValue: string) => {
        const newInputs = [...inputs];
        newInputs[index] = { ...newInputs[index], [field]: newValue };
        onChange(newInputs);
    };

    return (
        <div className="space-y-2">
            {inputs.map((input, index) => {
                const isValidName = input.name === '' || isValidPythonIdentifier(input.name);
                const isDuplicate = inputs.filter(i => i.name === input.name && input.name !== '').length > 1;

                return (
                    <div key={index} className="flex items-start gap-2">
                        {/* Variable name input */}
                        <div className="flex-shrink-0 w-28">
                            <input
                                type="text"
                                value={input.name}
                                onChange={(e) => updateInput(index, 'name', e.target.value)}
                                placeholder="var_name"
                                className={`w-full px-2 py-1.5 text-xs font-mono bg-foreground/[0.02] border rounded text-foreground/80 placeholder:text-[hsl(var(--placeholder))] focus:outline-none transition-all ${
                                    !isValidName || isDuplicate
                                        ? 'border-red-500/50 focus:border-red-500/70'
                                        : 'border-border dark:border-white/[0.05] focus:border-border dark:focus:border-white/[0.15]'
                                }`}
                                title={
                                    !isValidName
                                        ? 'Must be a valid Python identifier'
                                        : isDuplicate
                                        ? 'Duplicate variable name'
                                        : 'Variable name'
                                }
                            />
                        </div>

                        {/* Equals sign */}
                        <span className="text-muted-foreground dark:text-zinc-500 text-xs pt-1.5">=</span>

                        {/* Value input (droppable) */}
                        <div className="flex-1 min-w-0">
                            <DroppableTextField
                                fieldKey={`${fieldKey}-${index}`}
                                value={input.value}
                                onChange={(newValue) => updateInput(index, 'value', newValue)}
                                placeholder="{{node.field}} or value"
                                className="text-xs py-1.5"
                            />
                        </div>

                        {/* Remove button */}
                        <button
                            type="button"
                            onClick={() => removeInput(index)}
                            className="flex-shrink-0 p-1.5 text-muted-foreground dark:text-zinc-500 hover:text-red-400 hover:bg-red-500/10 rounded transition-colors"
                            title="Remove input"
                        >
                            <Trash2 className="w-3.5 h-3.5" />
                        </button>
                    </div>
                );
            })}

            {/* Add input button */}
            <button
                type="button"
                onClick={addInput}
                className="flex items-center gap-1.5 px-2 py-1 text-xs text-muted-foreground hover:text-foreground/80 hover:bg-foreground/[0.04] rounded transition-colors"
            >
                <Plus className="w-3.5 h-3.5" />
                <span>Add input</span>
            </button>

            {/* Help text */}
            {inputs.length === 0 && (
                <p className="text-[10px] text-muted-foreground/70 dark:text-zinc-600 mt-1">
                    Define variables to use in your function. Drag values from the Input panel.
                </p>
            )}
        </div>
    );
}
