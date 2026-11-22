// SwitchCasesEditor - Widget for defining switch cases with match values.
// Each case value doubles as both the match string and the output handle name.
// Used by the switch node to define multi-way branching.

import { Plus, Trash2 } from 'lucide-react';
import { DroppableTextField } from './DroppableTextField';
import { decodeLegacyHtmlEntities } from './legacyConfigParsing';

interface SwitchCase {
    value: string;
}

interface SwitchCasesEditorProps {
    value: SwitchCase[];
    onChange: (cases: SwitchCase[]) => void;
    fieldKey: string;
}

function parseCases(value: unknown): SwitchCase[] {
    if (Array.isArray(value)) {
        return value;
    }
    if (typeof value === 'string' && value.trim()) {
        try {
            const decoded = decodeLegacyHtmlEntities(value);
            const parsed = JSON.parse(decoded);
            if (Array.isArray(parsed)) {
                return parsed;
            }
        } catch {
            // Failed to parse
        }
    }
    return [];
}

export function SwitchCasesEditor({ value, onChange, fieldKey }: SwitchCasesEditorProps) {
    const cases = parseCases(value);

    const addCase = () => {
        onChange([...cases, { value: '' }]);
    };

    const removeCase = (index: number) => {
        onChange(cases.filter((_, i) => i !== index));
    };

    const updateCase = (index: number, newValue: string) => {
        const newCases = [...cases];
        newCases[index] = { value: newValue };
        onChange(newCases);
    };

    return (
        <div className="space-y-2">
            {cases.map((switchCase, index) => {
                const isDuplicate = switchCase.value !== '' &&
                    cases.filter(c => c.value === switchCase.value).length > 1;

                return (
                    <div key={index} className="flex items-start gap-2">
                        <div className="flex-1 min-w-0">
                            <DroppableTextField
                                fieldKey={`${fieldKey}-value-${index}`}
                                value={switchCase.value}
                                onChange={(newValue) => updateCase(index, newValue)}
                                placeholder="Match value"
                                className={`text-xs py-1.5 ${isDuplicate ? '!border-red-500/50' : ''}`}
                            />
                        </div>

                        <button
                            type="button"
                            onClick={() => removeCase(index)}
                            className="flex-shrink-0 p-1.5 text-muted-foreground dark:text-zinc-500 hover:text-red-400 hover:bg-red-500/10 rounded transition-colors"
                            title="Remove case"
                        >
                            <Trash2 className="w-3.5 h-3.5" />
                        </button>
                    </div>
                );
            })}

            <button
                type="button"
                onClick={addCase}
                className="flex items-center gap-1.5 px-2 py-1 text-xs text-muted-foreground hover:text-foreground/80 hover:bg-foreground/[0.04] rounded transition-colors"
            >
                <Plus className="w-3.5 h-3.5" />
                <span>Add case</span>
            </button>

            <p className="text-[10px] text-muted-foreground/70 dark:text-zinc-600 mt-1">
                Each case creates an output handle. Unmatched values flow out the
                always-present <span className="italic">default</span> handle.
            </p>
        </div>
    );
}
