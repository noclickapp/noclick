// What every inline component in the coordinator's thread is made of. A card is for an object NoClick is showing you
// (an agent, a number, an approval), never a box around a form; its header names the object, its body shows it, and
// its actions sit at the foot with no rule above them. Once it's done, a card folds to a one-line receipt so the
// thread reads as a history rather than a stack of forms. Colour comes from app marks and channels only; status is
// ink, with red kept for failure.
import { useEffect, useState, type ReactNode } from 'react';
import { Check, Loader2 } from 'lucide-react';
import { cn } from '~/lib/utils';
import { DISPLAY } from '~/components/shell/titles';

/** How wide a card runs in the thread: what stacks with one lines up to it. */
export const CARD_WIDTH = 'w-full max-w-[560px]';
export const CARD = cn(CARD_WIDTH, 'rounded-2xl border border-border bg-card dark:border-foreground/[0.08] dark:bg-foreground/[0.03]');

const PILL =
    'inline-flex h-8 shrink-0 items-center justify-center gap-1.5 rounded-full px-3.5 text-[13px] font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50';
export const PILL_PRIMARY = cn(PILL, 'bg-primary text-primary-foreground hover:opacity-90');
export const PILL_SECONDARY = cn(PILL, 'bg-secondary text-foreground hover:bg-accent dark:bg-foreground/[0.07] dark:hover:bg-foreground/[0.11]');
export const PILL_QUIET = cn(PILL, 'px-3 text-muted-foreground hover:bg-foreground/[0.05] hover:text-foreground');

/** A card for one object: its mark, its name, a line of what it is, then what it shows and what you can do. A name
 *  alone sits level with the mark; `display` sets it in the brand serif, for a thing you play or open (a recording).
 *  `kind` names what the object is after its name (Agent, Channel) where its mark alone doesn't say. */
export function InlineCard({
    lead,
    title,
    kind,
    meta,
    aside,
    children,
    actions,
    display = false,
    className,
}: {
    lead?: ReactNode;
    title: ReactNode;
    kind?: string;
    meta?: ReactNode;
    aside?: ReactNode;
    children?: ReactNode;
    actions?: ReactNode;
    display?: boolean;
    className?: string;
}) {
    return (
        <section className={cn(CARD, 'px-4 py-3.5', className)}>
            <header className={cn('flex gap-3', meta ? 'items-start' : 'items-center')}>
                {lead && <span className={cn('shrink-0', meta && 'mt-0.5')}>{lead}</span>}
                <div className="min-w-0 flex-1">
                    <div className={display ? 'text-[21px] leading-[1.15]' : 'text-[14.5px] leading-snug'}>
                        <h3 className={cn(display ? cn(DISPLAY, 'text-foreground') : 'font-medium tracking-[-0.005em] text-foreground', kind && 'inline')}>{title}</h3>
                        {kind && (
                            <span className="ml-2 inline-block rounded-full bg-foreground/[0.06] px-2 align-[1px] text-[11.5px] font-medium leading-[18px] text-foreground/65 dark:bg-foreground/[0.09]" data-testid="card-kind">
                                {kind}
                            </span>
                        )}
                    </div>
                    {meta && <p className="mt-0.5 text-[13px] leading-snug text-muted-foreground">{meta}</p>}
                </div>
                {aside && <div className="shrink-0">{aside}</div>}
            </header>
            {children && <div className="mt-3">{children}</div>}
            {actions && <div className="mt-3.5 flex flex-wrap items-center gap-2">{actions}</div>}
        </section>
    );
}

/** Rows of like things inside a card (apps, numbers, files), one hairline between each. */
export function Rows({ children, className }: { children: ReactNode; className?: string }) {
    return <div className={cn('divide-y divide-border dark:divide-foreground/[0.07]', className)}>{children}</div>;
}

export function Row({ lead, title, detail, aside, className }: { lead?: ReactNode; title: ReactNode; detail?: ReactNode; aside?: ReactNode; className?: string }) {
    return (
        <div className={cn('flex min-h-[52px] items-center gap-3 py-2', className)}>
            {lead && <span className="shrink-0">{lead}</span>}
            <div className="min-w-0 flex-1">
                <div className="truncate text-[14px] text-foreground">{title}</div>
                {detail && <div className="truncate text-[12.5px] text-muted-foreground">{detail}</div>}
            </div>
            {aside && <div className="flex shrink-0 items-center gap-2">{aside}</div>}
        </div>
    );
}

/** A finished card's whole story in one line: what happened, and the one thing you might do next. */
export function Receipt({ lead, children, action, tone = 'done' }: { lead?: ReactNode; children: ReactNode; action?: ReactNode; tone?: 'done' | 'info' }) {
    return (
        <div className="flex max-w-[560px] items-center gap-2 text-[13.5px] text-muted-foreground">
            {lead ?? (tone === 'done' ? <Check className="h-4 w-4 shrink-0 text-foreground/70" strokeWidth={2.25} /> : null)}
            <span className="min-w-0 flex-1 truncate">{children}</span>
            {action}
        </div>
    );
}

/** Ink status: done, working, or (only) failed in red. `mark` stands in for the state's own mark (a build's working
 *  mark), null for none. */
export function Status({ state, mark, children }: { state: 'done' | 'working' | 'failed' | 'idle'; mark?: ReactNode; children: ReactNode }) {
    return (
        <span
            className={cn(
                'inline-flex items-center gap-1.5 text-[12.5px]',
                state === 'failed' ? 'text-red-600 dark:text-red-400' : state === 'idle' ? 'text-muted-foreground' : 'text-foreground/75'
            )}
        >
            {mark !== undefined ? mark : state === 'done' ? <Check className="h-3.5 w-3.5" strokeWidth={2.5} /> : state === 'working' && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
            {children}
        </span>
    );
}

/** A neutral round tile for things NoClick owns that have no brand (a phone line, a domain, a file). */
export function GlyphTile({ children, className }: { children: ReactNode; className?: string }) {
    return (
        <span className={cn('grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-foreground/[0.06] text-foreground/80 dark:bg-foreground/[0.08]', className)}>
            {children}
        </span>
    );
}

/** "Gmail, Slack and Calendar". */
export function listOf(items: string[]): string {
    return items.length < 2 ? items.join('') : `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`;
}

// ── Parts of work that takes a while ─────────────────────────────────────────

export type StepState = 'done' | 'active' | 'queued' | 'failed';

export interface Step {
    label: ReactNode;
    /** How it reads while it's happening or still to come ("Writing the brief"); its detail shows once done. */
    doing?: ReactNode;
    detail?: ReactNode;
    /** The app the step happens in, when it's one. */
    mark?: ReactNode;
    state: StepState;
}

/** What a piece of work has done, is doing, and will do next. */
export function StepList({ steps }: { steps: Step[] }) {
    return (
        <ol className="space-y-1.5">
            {steps.map((step, i) => (
                <li key={i} className={cn('flex items-start gap-2.5 text-[14px] leading-snug transition-opacity', step.state === 'queued' && 'opacity-40')}>
                    <span className="mt-[2px] grid h-4 w-4 shrink-0 place-items-center">
                        {step.state === 'done' ? (
                            <Check className="h-3.5 w-3.5 text-foreground/75" strokeWidth={2.5} />
                        ) : step.state === 'active' ? (
                            <Loader2 className="h-3.5 w-3.5 animate-spin text-foreground/70" />
                        ) : step.state === 'failed' ? (
                            <span className="h-2 w-2 rounded-full bg-red-500" />
                        ) : (
                            <span className="h-1.5 w-1.5 rounded-full bg-foreground/30" />
                        )}
                    </span>
                    {step.mark && <span className="mt-[1px] shrink-0">{step.mark}</span>}
                    <span className="min-w-0">
                        <span className={step.state === 'failed' ? 'text-red-600 dark:text-red-400' : 'text-foreground'}>{step.state === 'done' || !step.doing ? step.label : step.doing}</span>
                        {step.detail && (step.state === 'done' || !step.doing) && <span className="text-muted-foreground"> · {step.detail}</span>}
                    </span>
                </li>
            ))}
        </ol>
    );
}

export function ProgressBar({ done, total }: { done: number; total: number }) {
    return (
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-foreground/[0.08]" role="progressbar" aria-valuenow={done} aria-valuemax={total}>
            <div className="h-full rounded-full bg-foreground/70 transition-[width] duration-500" style={{ width: `${Math.min(100, (done / total) * 100)}%` }} />
        </div>
    );
}

/** A pulse that says "this is happening now". */
export function LiveDot({ className }: { className?: string }) {
    return (
        <span className={cn('relative inline-flex h-2 w-2 shrink-0', className)} aria-hidden="true">
            <span className="absolute inset-0 animate-ping rounded-full bg-foreground/40 motion-reduce:animate-none" />
            <span className="relative h-2 w-2 rounded-full bg-foreground/80" />
        </span>
    );
}

/** m:ss (h:mm:ss past an hour) since `since`, ticking while `running`; up to `until` once that's known. */
export function useElapsed(since: number, running: boolean, until?: number): string {
    const [now, setNow] = useState(() => Date.now());
    useEffect(() => {
        if (!running) return;
        const t = window.setInterval(() => setNow(Date.now()), 1000);
        return () => window.clearInterval(t);
    }, [running]);
    const total = Math.max(0, Math.floor(((until ?? now) - since) / 1000));
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const sec = String(total % 60).padStart(2, '0');
    return h ? `${h}:${String(m).padStart(2, '0')}:${sec}` : `${m}:${sec}`;
}
