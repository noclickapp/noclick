// The seam the Automations page shows an agent's monthly budget through. An automation that runs one of the account's
// platform agents shows this month's spend against its budget in place of its node count, on its card and its row,
// opening an editor in place, and its Edit dialog has a Budget field. A deployment registers a Host (lazy), mounted once
// beside the page, that reads the agents and publishes their budgets with the pieces that draw them; without one every
// automation keeps its node count.
import { Suspense, useSyncExternalStore, type ComponentType } from 'react';

export interface AutomationBudget {
    agentId: string;
    /** Dollars a month; null without a budget. */
    budgetUsd: number | null;
    /** This month's spend in dollars (with a budget, the agents it started included): undefined until read, null when
     *  it couldn't be. */
    spentUsd: number | null | undefined;
    /** Sets the budget, or removes it (null); throws an Error saying why it couldn't. */
    save(budgetUsd: number | null): Promise<void>;
}

export interface AutomationBudgets {
    /** By the id of the workflow each agent runs on. */
    byWorkflow: ReadonlyMap<string, AutomationBudget>;
    /** The pill on its card and its row: the spend against the budget, opening the editor. */
    Pill: ComponentType<{ budget: AutomationBudget; variant: 'card' | 'row' }>;
    /** The Budget field in its Edit dialog, saved with the dialog (`useSaveWithItem`). */
    Field: ComponentType<{ budget: AutomationBudget }>;
}

let Host: ComponentType | null = null;
let published: AutomationBudgets | null = null;
const listeners = new Set<() => void>();

/** The deployment's Host: reads the account's agents and publishes their budgets (`publishAutomationBudgets`). */
export function registerAutomationBudgets(host: ComponentType): void {
    Host = host;
}

/** What the Host read, for the page; null takes it back. */
export function publishAutomationBudgets(value: AutomationBudgets | null): void {
    published = value;
    listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
    listeners.add(listener);
    return () => listeners.delete(listener);
}

/** The registered Host, mounted once beside the Automations page (nothing without one). Never around the page: it
 *  loads lazily, and the page must not remount when it arrives. */
export function AutomationBudgetsHost() {
    if (!Host) return null;
    return (
        <Suspense fallback={null}>
            <Host />
        </Suspense>
    );
}

/** The budget of the automation `workflowId`, with what draws it, when it runs a platform agent; else null. */
export function useAutomationBudget(workflowId: string): ({ budget: AutomationBudget } & Pick<AutomationBudgets, 'Pill' | 'Field'>) | null {
    const budgets = useSyncExternalStore(subscribe, () => published, () => null);
    const budget = budgets?.byWorkflow.get(workflowId);
    return budgets && budget ? { budget, Pill: budgets.Pill, Field: budgets.Field } : null;
}

/** The Budget field of the automation `workflowId`'s Edit dialog, when it runs a platform agent; else nothing. */
export function AutomationBudgetField({ workflowId }: { workflowId: string }) {
    const budgeted = useAutomationBudget(workflowId);
    return budgeted ? <budgeted.Field budget={budgeted.budget} /> : null;
}
