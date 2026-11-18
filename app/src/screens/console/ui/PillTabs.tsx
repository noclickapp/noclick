// NoClick's pill filters as navigation: the hubs' tabs (Activity, Settings,
// Resources) and any list's segment switch. Selected is the solid pill, the
// rest a faint wash, as on /templates.
import type { ReactNode } from 'react';
import * as Tabs from '@radix-ui/react-tabs';
import { Link } from 'react-router';
import { cn } from '@/ui/utils';

export interface PillTab {
    id: string;
    label: ReactNode;
    href: string;
    count?: number | null;
}

export const PILL = 'inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full px-3.5 text-xs font-medium transition-colors';
export const PILL_IDLE = 'bg-secondary text-foreground/70 hover:bg-accent hover:text-foreground dark:bg-foreground/[0.05] dark:text-muted-foreground dark:hover:bg-foreground/[0.09] dark:hover:text-foreground';
export const PILL_ACTIVE = 'bg-foreground text-background';

export function PillTabs({ label, tabs, active, className }: { label: string; tabs: readonly PillTab[]; active: string; className?: string }) {
    return (
        <nav aria-label={label} className={cn('flex gap-1.5 overflow-x-auto', className)}>
            {tabs.map((t) => (
                <Link key={t.id} to={t.href} aria-current={t.id === active ? 'page' : undefined} className={cn(PILL, t.id === active ? PILL_ACTIVE : PILL_IDLE)}>
                    {t.label}
                    {t.count != null && t.count > 0 && <span className="tabular-nums opacity-60">{t.count}</span>}
                </Link>
            ))}
        </nav>
    );
}

/** The same pills as in-page tabs bound to a value (the caller keeps it in the URL). They wrap rather than scroll, so no tab hides past an edge. */
export function PillSwitch({ tabs, value, onChange, label, className }: { tabs: readonly { id: string; label: ReactNode }[]; value: string; onChange: (id: string) => void; label: string; className?: string }) {
    return (
        <Tabs.Root value={value} onValueChange={onChange} className={className}>
            <Tabs.List aria-label={label} className="flex flex-wrap gap-1.5">
                {tabs.map((t) => (
                    <Tabs.Trigger key={t.id} value={t.id} className={cn(PILL, 'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring', t.id === value ? PILL_ACTIVE : PILL_IDLE)}>
                        {t.label}
                    </Tabs.Trigger>
                ))}
            </Tabs.List>
        </Tabs.Root>
    );
}

/** The rounded search field from /templates, for a `<label>` around an icon and an input. */
export const SEARCH_PILL =
    'flex h-8 min-w-0 items-center gap-2 rounded-full border border-foreground/[0.07] bg-foreground/[0.025] px-3.5 transition-colors focus-within:border-foreground/[0.14] focus-within:bg-foreground/[0.05]';
