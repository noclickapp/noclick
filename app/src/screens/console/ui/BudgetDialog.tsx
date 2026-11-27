// A monthly budget, changed in a dialog: an app's and an agent's page open it from their spend's "Change budget".
import { useEffect, useState, type ReactNode } from 'react';
import { cn } from '@/ui/utils';
import { errorText } from '@/screens/console/lib/errorText';
import { INPUT, LabeledInput } from '../pages/resources/shared';
import { ConsoleButton } from './Button';
import { ConsoleDialog } from './ConsoleDialog';

export function BudgetDialog({
    open,
    onOpenChange,
    current,
    description,
    note,
    removable,
    onSave,
}: {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    current: number | null;
    /** What the budget counts, and what happens at it. */
    description: string;
    /** A line under the amount (whose cap it counts toward). */
    note?: ReactNode;
    /** Whether it may have no budget at all. */
    removable: boolean;
    /** Saves it (null: none), throwing what the API refused. */
    onSave: (budget: number | null) => Promise<void>;
}) {
    const [text, setText] = useState('');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);
    useEffect(() => {
        if (!open) return;
        setText(current == null ? '' : String(current));
        setError(null);
    }, [open, current]);
    const amount = Number(text.trim());
    const valid = text.trim() !== '' && Number.isFinite(amount) && amount >= 0;
    const save = async (budget: number | null) => {
        setBusy(true);
        setError(null);
        try {
            await onSave(budget);
            onOpenChange(false);
        } catch (e) {
            setError(errorText(e));
        } finally {
            setBusy(false);
        }
    };
    return (
        <ConsoleDialog
            open={open}
            onOpenChange={onOpenChange}
            title="Monthly budget"
            description={description}
            footer={
                <>
                    {current != null && removable && (
                        <ConsoleButton disabled={busy} onClick={() => void save(null)}>
                            Remove budget
                        </ConsoleButton>
                    )}
                    <ConsoleButton variant="primary" disabled={busy || !valid} onClick={() => void save(amount)}>
                        {busy ? 'Saving…' : 'Save'}
                    </ConsoleButton>
                </>
            }
        >
            <form
                className="flex flex-col gap-3"
                onSubmit={(e) => {
                    e.preventDefault();
                    if (valid) void save(amount);
                }}
            >
                <LabeledInput label="Budget in USD" id="monthly-budget">
                    <input id="monthly-budget" className={cn(INPUT, 'tabular-nums')} inputMode="decimal" value={text} onChange={(e) => setText(e.target.value)} placeholder="25" autoComplete="off" />
                </LabeledInput>
                {note && <p className="m-0 text-[12px] text-muted-foreground">{note}</p>}
                {error && <p className="m-0 text-[12px] text-red-600 dark:text-red-400">{error}</p>}
            </form>
        </ConsoleDialog>
    );
}
