// A website's monthly budget on its page under Resources (GET /v1/projects/{id}/usage, PATCH /v1/projects/{id}): what
// it spent this month against it, what happens at it, and a way to change it. Every app made through the API has one,
// its maker's or $10; at it the app's paid calls stop while its pages keep serving, and at twice it its pages pause.
import { useEffect, useId, useState, type FormEvent } from 'react';
import { Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { BUTTON_GHOST, BUTTON_PRIMARY, BUTTON_SECONDARY } from '@/ui/buttons';
import { FIELD, FIELD_LABEL } from '@/ui/fields';
import { ShellDialog } from '@/ui/ShellDialog';
import { usePlatformResources } from './platform';
import { Section } from './ui';
import { errorText } from '@/screens/console/pages/resources/shared';
import { CapMeter } from '@/screens/console/ui/CapMeter';
import { useV1 } from '@/sdk/useV1';
import { formatMoney } from '@/screens/console/lib/format';
import type { Project } from 'noclick';

/** The day budgets reset: the first of the month after the one its usage reads. */
function resets(periodStart: Date | null): string {
    const start = periodStart ?? new Date();
    return new Date(Date.UTC(start.getUTCFullYear(), start.getUTCMonth() + 1, 1)).toLocaleDateString('en-US', { month: 'long', day: 'numeric', timeZone: 'UTC' });
}

function BudgetDialog({ project, open, onOpenChange }: { project: Project; open: boolean; onOpenChange: (open: boolean) => void }) {
    const platform = usePlatformResources();
    const fieldId = useId();
    const current = project.budgetUsdPerMonth;
    const [text, setText] = useState('');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>(undefined);
    useEffect(() => {
        if (!open) return;
        setText(current == null ? '' : String(current));
        setError(undefined);
    }, [open, current]);
    const amount = Number(text.trim());
    const valid = text.trim() !== '' && Number.isFinite(amount) && amount >= 0;
    const save = async (budget: number | null) => {
        setBusy(true);
        setError(undefined);
        try {
            await project.update({ budgetUsdPerMonth: budget });
            platform?.refresh();
            toast(budget == null ? `${project.name} has no budget now` : `${project.name} may spend ${formatMoney(budget)} a month`);
            onOpenChange(false);
        } catch (e) {
            setError(e);
        } finally {
            setBusy(false);
        }
    };
    const submit = (e: FormEvent<HTMLFormElement>) => {
        e.preventDefault();
        if (valid && !busy) void save(amount);
    };
    return (
        <ShellDialog
            open={open}
            onOpenChange={onOpenChange}
            title="Monthly budget"
            description={`The most ${project.name} may spend in a month, everything its code does included.`}
            onSubmit={submit}
            footer={
                <>
                    {/* An app with code always has a budget; only one NoClick publishes may have none. */}
                    {current != null && project.published && (
                        <button type="button" className={BUTTON_GHOST} disabled={busy} onClick={() => void save(null)}>
                            Remove budget
                        </button>
                    )}
                    <button type="submit" className={BUTTON_PRIMARY} disabled={!valid || busy}>
                        {busy && <Loader2 className="h-4 w-4 animate-spin" />}
                        Save
                    </button>
                </>
            }
        >
            <label htmlFor={fieldId} className={FIELD_LABEL}>
                Budget in dollars
            </label>
            <input id={fieldId} className={FIELD} inputMode="decimal" value={text} onChange={(e) => setText(e.target.value)} placeholder="20" autoComplete="off" />
            <p className="mt-1.5 text-[12.5px] text-muted-foreground">At it, its AI, agent turns, email and writes stop until the month turns, while its pages keep serving. At twice it, its pages pause too.</p>
            {error !== undefined && (
                <p role="alert" className="mt-3 text-[13.5px] text-red-600 dark:text-red-400">
                    {errorText(error)}
                </p>
            )}
        </ShellDialog>
    );
}

export function AppBudget({ project }: { project: Project }) {
    const [editing, setEditing] = useState(false);
    const usage = useV1(`resources:projects/${project.id}/usage`, () => project.usage());
    const budget = project.budgetUsdPerMonth;
    const used = usage.data;
    return (
        <Section
            title="Monthly budget"
            meta={budget == null ? 'None' : formatMoney(budget)}
            action={
                <button type="button" className={BUTTON_SECONDARY} onClick={() => setEditing(true)}>
                    {budget == null ? 'Set budget' : 'Change'}
                </button>
            }
        >
            <div data-testid="app-budget" className="flex max-w-[72ch] flex-col gap-2 text-[13.5px] text-muted-foreground">
                {usage.error !== undefined && !used ? (
                    <p role="alert">
                        {errorText(usage.error)}{' '}
                        <button type="button" onClick={() => void usage.refresh()} className="font-medium text-foreground underline underline-offset-4">
                            Try again
                        </button>
                    </p>
                ) : used ? (
                    <>
                        {budget != null ? (
                            <CapMeter spent={used.usd} cap={budget} className="w-full" />
                        ) : (
                            <p className="m-0">
                                <span className="font-medium tabular-nums text-foreground">{formatMoney(used.usd)}</span> spent this month.
                            </p>
                        )}
                        {used.limitedBy === 'project' ? (
                            <p role="status" className="m-0 text-foreground">
                                Its budget is used up: its AI, agent turns, email and writes are stopped until {resets(used.periodStart)}, while its pages keep serving. They pause at twice the budget.
                            </p>
                        ) : (
                            <p className="m-0">
                                {budget == null
                                    ? 'It has no budget: nothing stops what its code spends but your balance.'
                                    : 'At the budget its paid calls stop until the month turns and its pages keep serving; at twice it its pages pause.'}
                            </p>
                        )}
                    </>
                ) : (
                    <span aria-busy className="h-5 w-48 animate-pulse rounded bg-foreground/[0.06]" />
                )}
            </div>
            <BudgetDialog project={project} open={editing} onOpenChange={setEditing} />
        </Section>
    );
}
