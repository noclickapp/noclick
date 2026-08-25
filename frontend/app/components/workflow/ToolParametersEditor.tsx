// ToolParametersEditor - Widget for defining tool parameters that the LLM can pass.
// Each parameter has a name, type, description, and required flag.
// These parameters are converted to JSON Schema format for LLM function calling.

import { Plus, Trash2 } from 'lucide-react';

interface ToolParameter {
    name: string;
    type: 'string' | 'number' | 'boolean' | 'object' | 'array';
    description: string;
    required: boolean;
}

interface ToolParametersEditorProps {
    value: ToolParameter[];
    onChange: (params: ToolParameter[]) => void;
    fieldKey: string;
}

const PARAM_TYPES = [
    { value: 'string', label: 'Text' },
    { value: 'number', label: 'Number' },
    { value: 'boolean', label: 'Boolean' },
    { value: 'object', label: 'Object' },
    { value: 'array', label: 'List' },
] as const;

// Validate identifier: starts with letter/underscore, followed by letters/digits/underscores
const isValidIdentifier = (name: string): boolean => {
    return /^[a-zA-Z_][a-zA-Z0-9_]*$/.test(name);
};

export function ToolParametersEditor({ value, onChange, fieldKey }: ToolParametersEditorProps) {
    const params = value || [];

    const addParameter = () => {
        // Generate a default name like param_1, param_2, etc.
        const existingNames = new Set(params.map(p => p.name));
        let counter = 1;
        while (existingNames.has(`param_${counter}`)) {
            counter++;
        }
        onChange([...params, { name: `param_${counter}`, type: 'string', description: '', required: true }]);
    };

    const removeParameter = (index: number) => {
        onChange(params.filter((_, i) => i !== index));
    };

    const updateParameter = (index: number, updates: Partial<ToolParameter>) => {
        const newParams = [...params];
        newParams[index] = { ...newParams[index], ...updates };
        onChange(newParams);
    };

    return (
        <div className="space-y-2">
            {params.map((param, index) => {
                const isValidName = param.name === '' || isValidIdentifier(param.name);
                const isDuplicate = params.filter(p => p.name === param.name && param.name !== '').length > 1;

                return (
                    <div key={index} className="p-2.5 rounded-lg border border-border dark:border-white/[0.05] bg-foreground/[0.02] space-y-2">
                        {/* Row 1: Name and Type */}
                        <div className="flex items-center gap-2">
                            {/* Parameter name */}
                            <div className="flex-1">
                                <input
                                    type="text"
                                    value={param.name}
                                    onChange={(e) => updateParameter(index, { name: e.target.value })}
                                    placeholder="parameter_name"
                                    className={`w-full px-2 py-1.5 text-xs font-mono bg-foreground/[0.02] border rounded text-foreground/80 placeholder:text-[hsl(var(--placeholder))] focus:outline-none transition-all ${
                                        !isValidName || isDuplicate
                                            ? 'border-red-500/50 focus:border-red-500/70'
                                            : 'border-border dark:border-white/[0.05] focus:border-border dark:focus:border-white/[0.15]'
                                    }`}
                                    title={
                                        !isValidName
                                            ? 'Must be a valid identifier (letters, numbers, underscores)'
                                            : isDuplicate
                                            ? 'Duplicate parameter name'
                                            : 'Parameter name'
                                    }
                                />
                            </div>

                            {/* Type dropdown */}
                            <select
                                value={param.type}
                                onChange={(e) => updateParameter(index, { type: e.target.value as ToolParameter['type'] })}
                                className="px-2 py-1.5 text-xs bg-foreground/[0.02] border border-border dark:border-white/[0.05] rounded text-foreground/80 focus:outline-none focus:border-border dark:focus:border-white/[0.15] transition-colors"
                            >
                                {PARAM_TYPES.map(t => (
                                    <option key={t.value} value={t.value} className="bg-card">
                                        {t.label}
                                    </option>
                                ))}
                            </select>

                            {/* Required toggle */}
                            <button
                                type="button"
                                onClick={() => updateParameter(index, { required: !param.required })}
                                className={`px-2 py-1 text-[10px] font-medium rounded transition-colors ${
                                    param.required
                                        ? 'bg-orange-500/20 text-orange-600 dark:text-orange-400 border border-orange-500/30'
                                        : 'bg-secondary dark:bg-zinc-700/30 text-muted-foreground dark:text-zinc-500 border border-muted-foreground/40 dark:border-zinc-600/30 hover:text-muted-foreground'
                                }`}
                                title={param.required ? 'Click to make optional' : 'Click to make required'}
                            >
                                {param.required ? 'Required' : 'Optional'}
                            </button>

                            {/* Remove button */}
                            <button
                                type="button"
                                onClick={() => removeParameter(index)}
                                className="p-1.5 text-muted-foreground dark:text-zinc-500 hover:text-red-400 hover:bg-red-500/10 rounded transition-colors"
                                title="Remove parameter"
                            >
                                <Trash2 className="w-3.5 h-3.5" />
                            </button>
                        </div>

                        {/* Row 2: Description */}
                        <input
                            type="text"
                            value={param.description}
                            onChange={(e) => updateParameter(index, { description: e.target.value })}
                            placeholder="Description for the LLM (e.g., 'The city to get weather for')"
                            className="w-full px-2 py-1.5 text-xs bg-foreground/[0.02] border border-border dark:border-white/[0.05] rounded text-foreground/80 placeholder:text-[hsl(var(--placeholder))] focus:outline-none focus:border-border dark:focus:border-white/[0.15] transition-colors"
                        />
                    </div>
                );
            })}

            {/* Add parameter button */}
            <button
                type="button"
                onClick={addParameter}
                className="flex items-center gap-1.5 px-2 py-1.5 text-xs text-muted-foreground hover:text-foreground/80 hover:bg-foreground/[0.04] rounded transition-colors border border-dashed border-border dark:border-zinc-700 hover:border-border dark:hover:border-zinc-600 w-full justify-center"
            >
                <Plus className="w-3.5 h-3.5" />
                <span>Add Parameter</span>
            </button>

            {/* Help text */}
            {params.length === 0 && (
                <p className="text-[10px] text-muted-foreground/70 dark:text-zinc-600 mt-1 text-center">
                    Define parameters the AI can pass when calling this tool.
                </p>
            )}
        </div>
    );
}
