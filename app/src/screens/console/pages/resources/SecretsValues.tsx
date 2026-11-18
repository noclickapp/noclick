// Writing a secret's values: key and value rows whose
// values are masked as you type and never shown again, checked before they're sent, and the
// "Set values" dialog that merges them into a secret or replaces what it holds.
import { useEffect, useState } from 'react';
import { Plus, X } from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '@/ui/utils';
import type { Secret } from 'noclick';
import { invalidateV1 } from '@/sdk/useV1';
import { ConsoleButton } from '../../ui/Button';
import { ConsoleDialog } from '../../ui/ConsoleDialog';
import { ErrorPanel } from '../../ui/ErrorPanel';
import { Segmented } from '../../ui/Segmented';
import { ActsFor, INPUT } from './shared';

export interface ValueRow {
    key: string;
    value: string;
}

export const emptyRow = (key = ''): ValueRow => ({ key, value: '' });

/** Why a key can't be saved, before the API is asked: its shape, or a name NoClick sets itself. */
export function secretKeyProblem(key: string): string | null {
    if (!key) return null;
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(key)) return 'Letters, digits and _, not starting with a digit.';
    if (['PATH', 'HOME', 'PYTHONPATH'].includes(key) || key.startsWith('LD_') || key.startsWith('NOCLICK_')) return `${key} is reserved: NoClick sets it in every sandbox and agent shell.`;
    return null;
}

/** The rows as values to send, or null while any row is unfinished, invalid or repeated. */
export function rowsToValues(rows: readonly ValueRow[]): Record<string, string> | null {
    const filled = rows.filter((r) => r.key || r.value);
    if (!filled.length) return null;
    const keys = filled.map((r) => r.key);
    if (filled.some((r) => !r.key || !r.value || secretKeyProblem(r.key)) || new Set(keys).size !== keys.length) return null;
    return Object.fromEntries(filled.map((r) => [r.key, r.value]));
}

/** Key and value rows; a value is a password field, so nothing typed is shown. */
export function ValueRows({ rows, onChange, lockedKey }: { rows: ValueRow[]; onChange: (rows: ValueRow[]) => void; lockedKey?: string | null }) {
    const set = (i: number, patch: Partial<ValueRow>) => onChange(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
    const seen = new Map<string, number>();
    rows.forEach((r) => r.key && seen.set(r.key, (seen.get(r.key) ?? 0) + 1));
    return (
        <div className="flex flex-col gap-2">
            <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_1.75rem] gap-2 text-[12px] font-medium text-muted-foreground">
                <span>Key</span>
                <span>Value</span>
            </div>
            {rows.map((r, i) => {
                const problem = secretKeyProblem(r.key) ?? ((seen.get(r.key) ?? 0) > 1 ? `${r.key} is listed twice.` : null);
                return (
                    <div key={i} className="flex flex-col gap-1">
                        <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_1.75rem] items-center gap-2">
                            <input
                                aria-label={`Key ${i + 1}`}
                                className={cn(INPUT, 'font-mono', problem && 'border-red-500/60')}
                                value={r.key}
                                disabled={lockedKey === r.key && i === 0}
                                onChange={(e) => set(i, { key: e.target.value.replace(/[^A-Za-z0-9_]/g, '_') })}
                                placeholder="OPENAI_API_KEY"
                                autoComplete="off"
                                spellCheck={false}
                            />
                            <input
                                aria-label={`Value of ${r.key || `key ${i + 1}`}`}
                                type="password"
                                className={cn(INPUT, 'font-mono')}
                                value={r.value}
                                onChange={(e) => set(i, { value: e.target.value })}
                                autoComplete="new-password"
                            />
                            <ConsoleButton
                                variant="ghost"
                                size="icon"
                                aria-label={`Remove row ${i + 1}`}
                                disabled={rows.length === 1}
                                onClick={() => onChange(rows.filter((_, j) => j !== i))}
                                icon={<X className="h-3.5 w-3.5" />}
                            />
                        </div>
                        {problem && <span className="text-[12px] text-red-600 dark:text-red-400">{problem}</span>}
                    </div>
                );
            })}
            <ConsoleButton variant="ghost" size="sm" className="self-start" onClick={() => onChange([...rows, emptyRow()])} icon={<Plus className="h-3.5 w-3.5" />}>
                Add a key
            </ConsoleButton>
        </div>
    );
}

type Mode = 'merge' | 'replace';

/** Set some of a secret's values (merge) or all of them (replace). Opened with a key, it replaces that one. */
export function SetValuesDialog({
    secret,
    open,
    initialKey,
    onOpenChange,
    onSaved,
}: {
    secret: Secret;
    open: boolean;
    initialKey: string | null;
    onOpenChange: (open: boolean) => void;
    onSaved: (secret: Secret) => void;
}) {
    const [rows, setRows] = useState<ValueRow[]>([emptyRow()]);
    const [mode, setMode] = useState<Mode>('merge');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>(undefined);
    useEffect(() => {
        if (!open) return;
        setRows([emptyRow(initialKey ?? '')]);
        setMode('merge');
        setError(undefined);
    }, [open, initialKey]);
    const values = rowsToValues(rows);
    const dropped = mode === 'replace' && values ? secret.keys.filter((k) => !(k in values)) : [];
    const save = async () => {
        if (!values) return;
        setBusy(true);
        setError(undefined);
        try {
            const saved = await secret.update(values, { replace: mode === 'replace' });
            setRows([emptyRow()]);
            invalidateV1('secrets');
            onSaved(saved);
            onOpenChange(false);
            const count = Object.keys(values).length;
            toast(`Saved ${count} ${count === 1 ? 'value' : 'values'} in ${secret.name}`, { description: 'Values are write-only: only the key names show from now on.' });
        } catch (e) {
            setError(e);
        } finally {
            setBusy(false);
        }
    };
    return (
        <ConsoleDialog
            open={open}
            onOpenChange={onOpenChange}
            title={initialKey ? `Replace ${initialKey}` : `Set values in ${secret.name}`}
            description="Values are write-only: once saved, nobody can read one back, here or through the API. New sandboxes get them at once, agents from their next turn, apps at their next deploy."
            footer={
                <ConsoleButton variant="primary" disabled={busy || !values} onClick={() => void save()}>
                    {busy ? 'Saving…' : 'Save'}
                </ConsoleButton>
            }
        >
            <form
                className="flex flex-col gap-4"
                onSubmit={(e) => {
                    e.preventDefault();
                    void save();
                }}
            >
                <ActsFor userId={secret.userId} />
                <ValueRows rows={rows} onChange={setRows} lockedKey={initialKey} />
                {!initialKey && (
                    <div className="flex flex-col gap-1.5">
                        <Segmented
                            label="How to save"
                            value={mode}
                            onChange={setMode}
                            className="self-start"
                            options={[
                                { value: 'merge', label: 'Merge' },
                                { value: 'replace', label: 'Replace all' },
                            ]}
                        />
                        <span className="text-[12px] text-muted-foreground">
                            {mode === 'merge'
                                ? 'The keys above are set; every other key is kept.'
                                : dropped.length
                                  ? `The secret holds exactly the keys above: ${dropped.join(', ')} ${dropped.length === 1 ? 'is' : 'are'} removed.`
                                  : 'The secret holds exactly the keys above.'}
                        </span>
                    </div>
                )}
                {error !== undefined && <ErrorPanel error={error} />}
            </form>
        </ConsoleDialog>
    );
}
