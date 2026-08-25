// EnvVarRowsEditor — the shared key/value rows editor for sandbox environment
// variables (STRIPE_KEY / value with a masked value input, add/remove rows).
// Extracted from AgentEnvVarsSection so the same editor drives all three surfaces:
// the agent config panel, the builder input drawer (interactive request), and the
// public /b bridge page (shareable-link request). Validation lives in agentEnvVars.ts.

import { type ReactElement } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import { SecretInput } from './SecretInput';
import type { EnvRow } from './agentEnvVars';

// Compact row field, sized to match DroppableTextField inside KeyValueEditor.
const rowInputClasses =
    'px-2 py-1.5 text-xs bg-card border border-input rounded-md text-foreground/80 placeholder:text-[hsl(var(--placeholder))] focus:outline-none focus:border-foreground/20 transition-colors';

export const emptyEnvRow = (): EnvRow => ({ key: '', value: '' });

interface EnvVarRowsEditorProps {
    rows: EnvRow[];
    onChange: (rows: EnvRow[]) => void;
    /** Optional fixed key names (from a builder request) shown as read-only key
     *  cells — the user only fills values. Omit for a free-form editor. */
    lockKeys?: boolean;
    keyPlaceholder?: string;
}

export function EnvVarRowsEditor({
    rows,
    onChange,
    lockKeys = false,
    keyPlaceholder = 'STRIPE_KEY',
}: EnvVarRowsEditorProps): ReactElement {
    const updateRow = (index: number, patch: Partial<EnvRow>) =>
        onChange(rows.map((r, i) => (i === index ? { ...r, ...patch } : r)));

    return (
        <div className="space-y-2">
            {rows.map((row, i) => (
                <div key={i} className="group flex items-center gap-1.5">
                    <input
                        type="text"
                        value={row.key}
                        onChange={e => updateRow(i, { key: e.target.value })}
                        placeholder={keyPlaceholder}
                        readOnly={lockKeys}
                        className={`${rowInputClasses} flex-1 min-w-0 font-mono ${lockKeys ? 'opacity-70 cursor-default' : ''}`}
                        spellCheck={false}
                        autoCapitalize="off"
                        autoCorrect="off"
                    />
                    <SecretInput
                        value={row.value}
                        onChange={e => updateRow(i, { value: e.target.value })}
                        placeholder="value"
                        className="flex-1 min-w-0"
                        inputClassName={`${rowInputClasses} w-full font-mono`}
                    />
                    {!lockKeys && (
                        <button
                            type="button"
                            onClick={() => onChange(rows.filter((_, j) => j !== i))}
                            className="flex-shrink-0 p-1.5 text-muted-foreground dark:text-zinc-500 hover:text-red-400 hover:bg-red-500/10 rounded transition-colors"
                            title="Remove variable"
                        >
                            <Trash2 className="w-3.5 h-3.5" />
                        </button>
                    )}
                </div>
            ))}

            {!lockKeys && (
                <button
                    type="button"
                    onClick={() => onChange([...rows, emptyEnvRow()])}
                    className="flex items-center gap-1.5 px-2 py-1.5 text-xs text-muted-foreground hover:text-foreground hover:bg-foreground/[0.04] rounded transition-colors border border-dashed border-border dark:border-zinc-700 hover:border-foreground/20 w-full justify-center"
                >
                    <Plus className="w-3.5 h-3.5" />
                    <span>Add variable</span>
                </button>
            )}
        </div>
    );
}
