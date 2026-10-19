// What every Settings section is built from, so the sections read as one page:
// the section's title and line (the shell pages' own header), and groups of
// rows, each a name and what it does with its control on the right.
import type { ReactNode } from 'react';
import { cn } from '~/lib/utils';
import { HAIRLINE } from '~/components/dashboard/primitives';
import { PAGE_TITLE } from '~/components/shell/titles';

/** The section's title, its line, and anything that belongs beside or under them. */
export function SettingsHeader({ title, description, actions, children }: { title: ReactNode; description?: ReactNode; actions?: ReactNode; children?: ReactNode }) {
    return (
        <header className="mb-8 flex min-w-0 flex-wrap items-start gap-x-6 gap-y-4">
            <div className="min-w-0 flex-1">
                <h2 className={PAGE_TITLE}>{title}</h2>
                {description ? <p className="mt-1 text-[14px] text-muted-foreground">{description}</p> : null}
                {children}
            </div>
            {actions && <div className="flex shrink-0 items-center gap-2 sm:pt-1.5">{actions}</div>}
        </header>
    );
}

/** A group's heading, for a section with more than one group. */
export function SettingsGroupTitle({ title, description, actions }: { title: ReactNode; description?: ReactNode; actions?: ReactNode }) {
    return (
        <div className="mb-3 flex min-w-0 items-end justify-between gap-4">
            <div className="min-w-0">
                <h3 className="text-[15px] font-semibold text-foreground">{title}</h3>
                {description ? <p className="mt-0.5 text-[13px] text-muted-foreground">{description}</p> : null}
            </div>
            {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </div>
    );
}

/** Rows that belong together, divided by hairlines; a quiet note may follow. */
export function SettingsGroup({ children, note, className }: { children: ReactNode; note?: ReactNode; className?: string }) {
    return (
        <div>
            <div className={cn('divide-y overflow-hidden rounded-2xl border bg-card dark:divide-foreground/[0.06] dark:bg-transparent', HAIRLINE, className)}>{children}</div>
            {note ? <p className="mt-2.5 px-1 text-[12.5px] text-muted-foreground">{note}</p> : null}
        </div>
    );
}

/** One setting: its name and what it does on the left, its control on the right. */
export function SettingsRow({ label, description, control, className }: { label: ReactNode; description?: ReactNode; control?: ReactNode; className?: string }) {
    return (
        <div className={cn('flex min-h-[64px] flex-wrap items-center gap-x-6 gap-y-3 px-5 py-3.5', className)}>
            <div className="min-w-0 flex-1">
                <div className="text-[14.5px] font-medium text-foreground">{label}</div>
                {description ? <div className="mt-0.5 text-[13px] text-muted-foreground">{description}</div> : null}
            </div>
            {control ? <div className="flex shrink-0 items-center gap-2">{control}</div> : null}
        </div>
    );
}

/** What a group says when it has nothing in it yet. */
export function SettingsEmpty({ children }: { children: ReactNode }) {
    return <div className="px-5 py-6 text-center text-[13.5px] text-muted-foreground">{children}</div>;
}
