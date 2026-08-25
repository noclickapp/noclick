// KeyValueEditor - Widget for editing a list of {key, value, enabled} rows,
// used by the HTTP Request node for headers and query parameters. Each value
// supports {{references}} via drag-and-drop (DroppableTextField). A per-row
// checkbox toggles a row off without deleting it. Added to give the HTTP node a
// proper key/value UI instead of a raw-JSON textarea.

import { Plus, Trash2 } from 'lucide-react';
import { DroppableTextField } from './DroppableTextField';
import { Checkbox } from '~/components/ui/checkbox';
import { decodeLegacyHtmlEntities } from './legacyConfigParsing';

interface KVRow {
    key: string;
    value: string;
    enabled: boolean;
}

interface KeyValueEditorProps {
    value: unknown;
    onChange: (rows: KVRow[]) => void;
    fieldKey: string;
    keyPlaceholder?: string;
    valuePlaceholder?: string;
    addLabel?: string;
}

// Accept the structured list (current shape), a JSON array string, and — for
// configs saved before this widget existed — a JSON object string/dict, which
// is shown as rows. HTML entities are decoded the same way VariableAssignments
// does (values can arrive entity-escaped from the MCP/XML path).
function parseRows(value: unknown): KVRow[] {
    const toRow = (r: any): KVRow => ({
        key: r?.key ?? '',
        value: r?.value ?? '',
        enabled: r?.enabled !== false,
    });

    if (Array.isArray(value)) return value.map(toRow);

    if (typeof value === 'string' && value.trim()) {
        try {
            const decoded = decodeLegacyHtmlEntities(value);
            const parsed = JSON.parse(decoded);
            if (Array.isArray(parsed)) return parsed.map(toRow);
            if (parsed && typeof parsed === 'object') {
                return Object.entries(parsed).map(([k, v]) => ({
                    key: k,
                    value: v == null ? '' : String(v),
                    enabled: true,
                }));
            }
        } catch {
            /* fall through to empty */
        }
    }
    return [];
}

export function KeyValueEditor({
    value,
    onChange,
    fieldKey,
    keyPlaceholder = 'Name',
    valuePlaceholder = '{{node.field}} or value',
    addLabel = 'Add',
}: KeyValueEditorProps) {
    const rows = parseRows(value);

    const addRow = () => onChange([...rows, { key: '', value: '', enabled: true }]);
    const removeRow = (index: number) => onChange(rows.filter((_, i) => i !== index));
    const updateRow = (index: number, patch: Partial<KVRow>) => {
        const next = [...rows];
        next[index] = { ...next[index], ...patch };
        onChange(next);
    };

    return (
        <div className="space-y-2">
            {rows.map((row, index) => (
                <div
                    key={index}
                    className={`group flex items-center gap-1.5 transition-opacity ${row.enabled ? '' : 'opacity-45'}`}
                >
                    <Checkbox
                        checked={row.enabled}
                        onCheckedChange={(c) => updateRow(index, { enabled: c === true })}
                        title={row.enabled ? 'Included — click to skip this row' : 'Skipped — click to include'}
                        className="flex-shrink-0 h-4 w-4 rounded border-foreground/25 data-[state=checked]:bg-primary data-[state=checked]:border-primary data-[state=checked]:text-primary-foreground [&_svg]:h-3 [&_svg]:w-3"
                    />
                    <div className="flex-1 min-w-0">
                        <DroppableTextField
                            fieldKey={`${fieldKey}-key-${index}`}
                            value={row.key}
                            onChange={(v) => updateRow(index, { key: v })}
                            placeholder={keyPlaceholder}
                            className="text-xs py-1.5 font-mono"
                        />
                    </div>
                    <div className="flex-1 min-w-0">
                        <DroppableTextField
                            fieldKey={`${fieldKey}-val-${index}`}
                            value={row.value}
                            onChange={(v) => updateRow(index, { value: v })}
                            placeholder={valuePlaceholder}
                            className="text-xs py-1.5"
                        />
                    </div>
                    <button
                        type="button"
                        onClick={() => removeRow(index)}
                        className="flex-shrink-0 p-1.5 text-muted-foreground dark:text-zinc-500 hover:text-red-400 hover:bg-red-500/10 rounded transition-colors"
                        title="Remove row"
                    >
                        <Trash2 className="w-3.5 h-3.5" />
                    </button>
                </div>
            ))}

            <button
                type="button"
                onClick={addRow}
                className="flex items-center gap-1.5 px-2 py-1.5 text-xs text-muted-foreground hover:text-foreground hover:bg-foreground/[0.04] rounded transition-colors border border-dashed border-border dark:border-zinc-700 hover:border-foreground/20 w-full justify-center"
            >
                <Plus className="w-3.5 h-3.5" />
                <span>{addLabel}</span>
            </button>
        </div>
    );
}
