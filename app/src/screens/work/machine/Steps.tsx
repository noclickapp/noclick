// Numbered steps that tick as something moves along, a line joining each dot to the next: Add your computer's pairing
// and a machine's purchase (quote, buy, start) both read as these. Each step is done, now, busy (a spinner), waiting,
// or an error.
import type { ReactNode } from 'react';
import { Check } from 'lucide-react';
import { cn } from '@/ui/utils';

export type StepStatus = 'done' | 'now' | 'busy' | 'wait' | 'error';
export interface Step {
    id: string;
    title: ReactNode;
    status: StepStatus;
    body: ReactNode;
}

export function Steps({ steps }: { steps: Step[] }) {
    return (
        <ol>
            {steps.map((s, i) => (
                <li key={s.id} data-testid={`step-${s.id}`} data-status={s.status} className="relative flex gap-3.5 pb-5 last:pb-1">
                    {i < steps.length - 1 && <span aria-hidden className={cn('absolute bottom-0 left-[13px] top-8 w-px', s.status === 'done' ? 'bg-foreground/30' : 'bg-border dark:bg-foreground/[0.1]')} />}
                    <StepDot n={i + 1} status={s.status} />
                    <div className="min-w-0 flex-1 pt-1">
                        <p className={cn('text-[14px] font-medium leading-tight', s.status === 'wait' ? 'text-muted-foreground' : s.status === 'error' ? 'text-red-600 dark:text-red-400' : 'text-foreground')}>{s.title}</p>
                        {s.body}
                    </div>
                </li>
            ))}
        </ol>
    );
}

function StepDot({ n, status }: { n: number; status: StepStatus }) {
    return (
        <span
            className={cn(
                'relative z-[1] grid h-[27px] w-[27px] shrink-0 place-items-center rounded-full text-[12.5px] font-medium tabular-nums',
                status === 'done' && 'bg-foreground text-background',
                status === 'now' && 'bg-card text-foreground ring-[1.5px] ring-inset ring-foreground dark:bg-sunken',
                status === 'busy' && 'bg-card text-foreground ring-1 ring-inset ring-foreground/20 dark:bg-sunken',
                status === 'wait' && 'bg-card text-muted-foreground ring-1 ring-inset ring-foreground/15 dark:bg-sunken',
                status === 'error' && 'bg-red-500/10 text-red-600 ring-1 ring-inset ring-red-500/40 dark:text-red-400'
            )}
        >
            {status === 'done' ? (
                <Check className="h-3.5 w-3.5" strokeWidth={2.5} />
            ) : status === 'busy' ? (
                <span aria-hidden className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-r-transparent text-foreground/70 [animation-duration:1.1s]" />
            ) : status === 'error' ? (
                '!'
            ) : (
                n
            )}
        </span>
    );
}
