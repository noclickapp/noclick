// What stands in the Usage page's slots (slots.ts) when no host fills them: each works on what the page read alone.
import { useContext } from 'react';
import { ExternalLink } from 'lucide-react';
import { fmtDuration } from '@/lib/formatters';
import { ConsoleContext } from '@/screens/console/hooks/useConsole';
import { addFundsUrl, NOCLICK_SITE, workflowUrl } from '@/screens/console/lib/site';
import { BUTTON_GHOST, BUTTON_PRIMARY, BUTTON_SECONDARY } from '@/ui/buttons';
import { ROWS } from '@/ui/primitives';
import { ShellDialog } from '@/ui/ShellDialog';
import { cn } from '@/ui/utils';
import { ZONE_LABEL, dayKey, dayLabel, money, planName, timeLabel, type UsageView } from './derive';
import type { ChargeRun } from './types';

/** NoClick's own site, as the console the page is drawn in names it (a page outside one links to noclick.com). */
function useSite(): string {
    return useContext(ConsoleContext)?.site ?? NOCLICK_SITE;
}

/** The balance as the page read it, and a link to add funds on NoClick, where they're added. */
export function BalanceOnNoClick({ view }: { view: UsageView }) {
    const site = useSite();
    const old = view.onOldPlan;
    const owed = view.balance < 0;
    const figure = old ? money(view.left) : view.hasBalance ? money(Math.abs(view.balance)) : '$0';
    const tier = view.snap.billing?.plan.tier ?? 'free';
    const title = old ? `${planName(tier)} credits left` : owed ? 'Owed' : 'Balance';
    const note = old ? null : owed ? 'Repaid from the next funds you add' : view.hasBalance ? null : 'No funds yet';
    return (
        <div className="min-w-0">
            <p className="text-[13px] font-medium text-muted-foreground">{title}</p>
            <div className="mt-2 flex items-center justify-between gap-4">
                <div className={cn('text-[32px] font-semibold leading-none tracking-[-0.03em] tabular-nums', owed ? 'text-red-600 dark:text-red-400' : 'text-foreground')}>{figure}</div>
                <a href={addFundsUrl(site)} target="_blank" rel="noreferrer" className={cn(BUTTON_SECONDARY, 'px-4')}>
                    Add funds on NoClick
                    <ExternalLink aria-hidden className="h-3.5 w-3.5" />
                </a>
            </div>
            {note && <p className="mt-2.5 text-[13px] text-muted-foreground">{note}</p>}
        </div>
    );
}

/** A charge's run as the charges read describes it, with its automation on NoClick for the rest. */
export function RunFacts({ run, onClose }: { run: ChargeRun; onClose: () => void }) {
    const site = useSite();
    const facts: { label: string; value: string }[] = [
        { label: 'Status', value: run.status },
        { label: 'Started', value: `${dayLabel(dayKey(run.startedAt), { weekday: true })}, ${timeLabel(run.startedAt)} ${ZONE_LABEL}` },
    ];
    if (run.durationMs != null) facts.push({ label: 'Took', value: fmtDuration(run.durationMs) });
    if (run.trigger) facts.push({ label: 'Started by', value: run.trigger });
    facts.push({ label: 'Steps', value: String(run.nodesExecuted) });
    if (run.error) facts.push({ label: 'Error', value: run.error });
    return (
        <ShellDialog
            open
            onOpenChange={(open) => !open && onClose()}
            title={run.workflow.name}
            description={`Run ${run.id.slice(0, 8)}`}
            footer={
                <>
                    <button type="button" onClick={onClose} className={BUTTON_GHOST}>
                        Close
                    </button>
                    <a href={workflowUrl(site, run.workflow.id)} target="_blank" rel="noreferrer" className={BUTTON_PRIMARY}>
                        <ExternalLink aria-hidden className="h-4 w-4" />
                        Open on NoClick
                    </a>
                </>
            }
        >
            <dl className={ROWS}>
                {facts.map((f) => (
                    <div key={f.label} className="grid grid-cols-[96px_minmax(0,1fr)] gap-4 py-2.5 text-[13.5px]">
                        <dt className="text-muted-foreground">{f.label}</dt>
                        <dd className="m-0 min-w-0 break-words text-foreground">{f.value}</dd>
                    </div>
                ))}
            </dl>
        </ShellDialog>
    );
}
