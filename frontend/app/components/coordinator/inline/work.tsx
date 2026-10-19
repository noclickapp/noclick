// The work itself, in the thread: what wants your OK before it runs, what a run did (or what stopped it), when
// something runs, and when NoClick will look again.
import type { ReactNode } from 'react';
import { Bell, CalendarClock } from 'lucide-react';
import { AutomationMark } from '~/components/shell/glyphs';
import { cn } from '~/lib/utils';
import { GlyphTile, InlineCard, Receipt, Status } from './primitives';

/** Something an account is about to do on your behalf, held for your OK: what, the details, and the decision. */
export function ApprovalCard({ lead, title, meta = 'Waiting for your OK', children, actions }: { lead?: ReactNode; title: ReactNode; meta?: ReactNode; children?: ReactNode; actions?: ReactNode }) {
    return (
        <InlineCard lead={lead} title={title} meta={meta} actions={actions}>
            {children}
        </InlineCard>
    );
}

export interface RunStep {
    label: string;
    /** Why it stopped here, on the step that failed. */
    error?: string;
}

/** A run: what each step did, or where it stopped and why. */
export function RunCard({ name, when, steps, failed, actions }: { name: string; when?: string; steps: RunStep[]; failed: boolean; actions?: ReactNode }) {
    return (
        <InlineCard
            lead={<AutomationMark className="mt-0.5 h-5 w-5" />}
            title={failed ? `${name} stopped` : `${name} ran`}
            meta={when}
            aside={failed ? <Status state="failed">Failed</Status> : <Status state="done">Done</Status>}
            actions={actions}
        >
            {steps.length > 0 && (
                <ol className="space-y-1">
                    {steps.map((step, i) => (
                        <li key={i} className={cn('flex items-baseline gap-2.5 text-[14px]', step.error ? 'text-red-600 dark:text-red-400' : 'text-foreground/85')}>
                            <span className="w-4 shrink-0 text-right text-[12px] tabular-nums text-muted-foreground">{i + 1}</span>
                            <span className="min-w-0 break-words">{step.error ? `${step.label}: ${step.error}` : step.label}</span>
                        </li>
                    ))}
                </ol>
            )}
        </InlineCard>
    );
}

/** When something runs, in words, with the next few times. */
export function ScheduleCard({ sentence, zone, next, actions }: { sentence: string; zone?: string; next: string[]; actions?: ReactNode }) {
    return (
        <InlineCard
            lead={
                <GlyphTile>
                    <CalendarClock className="h-4 w-4" />
                </GlyphTile>
            }
            title={sentence}
            meta={zone}
            actions={actions}
        >
            {next.length > 0 && (
                <>
                    <p className="text-[13px] text-muted-foreground">Next</p>
                    <ul className="mt-1 flex flex-wrap gap-x-5 gap-y-1 text-[14px] tabular-nums text-foreground">
                        {next.map((when) => (
                            <li key={when}>{when}</li>
                        ))}
                    </ul>
                </>
            )}
        </InlineCard>
    );
}

/** NoClick promising to look again: when, about what, and the way to call it off. */
export function CheckBackLine({ when, what, action }: { when: string; what: string; action?: ReactNode }) {
    return (
        <Receipt tone="info" lead={<Bell className="h-4 w-4 shrink-0 text-foreground/60" />} action={action}>
            Checking back {when}: {what}
        </Receipt>
    );
}
