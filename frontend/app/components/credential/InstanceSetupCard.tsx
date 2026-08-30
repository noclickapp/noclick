// The one card for "this instance needs something from its operator" asks —
// an OAuth app, a service key — so the credential panel, the builder and the
// <ask> drawer all set them up the same way: what to do, in two or three
// steps, then the form. Both forms share these styles so they line up.
import type { ReactNode } from 'react';

export const INSTANCE_FORM = {
    card: 'p-4 rounded-lg bg-muted/60 dark:bg-zinc-900/60 border border-border space-y-4',
    title: 'text-sm font-medium text-foreground',
    steps: 'mt-1.5 list-decimal space-y-0.5 pl-4 text-xs text-muted-foreground/80 dark:text-zinc-400',
    chip: 'inline-flex items-center gap-1.5 rounded-md border border-border bg-foreground/[0.06] px-2.5 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-foreground/[0.12]',
    label: 'block text-xs font-medium text-muted-foreground dark:text-white/50 mb-1.5',
    input:
        'w-full h-9 px-3 text-sm bg-foreground/[0.035] dark:bg-white/[0.045] border border-input dark:border-white/[0.12] rounded-lg ' +
        'text-foreground placeholder:text-[hsl(var(--placeholder))] outline-none ' +
        'focus:border-muted-foreground/40 dark:focus:border-white/20 font-mono',
    primaryButton:
        'h-9 px-4 text-sm font-medium bg-primary text-primary-foreground rounded-lg hover:bg-foreground/90 disabled:opacity-40 transition-colors',
    note: 'text-xs text-muted-foreground/60 dark:text-white/25 ml-auto',
} as const;

export function InstanceSetupCard({
    title,
    steps,
    children,
}: {
    title: string;
    steps: string[];
    children: ReactNode;
}) {
    return (
        <div className={INSTANCE_FORM.card}>
            <div>
                <div className={INSTANCE_FORM.title}>{title}</div>
                <ol className={INSTANCE_FORM.steps}>
                    {steps.map((step) => (
                        <li key={step}>{step}</li>
                    ))}
                </ol>
            </div>
            {children}
        </div>
    );
}
