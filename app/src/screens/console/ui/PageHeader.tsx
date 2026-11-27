// A page's title block: the way back above it on a detail page (`Resources ›`),
// the title in the brand face, one sentence under it, and the page's one or two
// actions on the right. A page's body can put its action up here with
// `PageActions`, so every create button sits in the same place.
import { createContext, useContext, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { ChevronRight } from 'lucide-react';
import { Link } from 'react-router';
import { cn } from '@/ui/utils';
import { sectionById, type SectionId } from '../sections';
import { PAGE_TITLE } from '@/ui/titles';

export interface Crumb {
    label: ReactNode;
    href?: string;
}

/** The page title's own actions slot, which a body below the header can fill. */
const ActionsSlot = createContext<{ slot: HTMLElement | null; setSlot: (el: HTMLElement | null) => void } | null>(null);

export function PageActionsProvider({ children }: { children: ReactNode }) {
    const [slot, setSlot] = useState<HTMLElement | null>(null);
    return <ActionsSlot.Provider value={{ slot, setSlot }}>{children}</ActionsSlot.Provider>;
}

/** Actions a page's body adds beside its title; outside a console page (a panel alone) they stay where they're rendered. */
export function PageActions({ children }: { children: ReactNode }) {
    const ctx = useContext(ActionsSlot);
    if (!ctx) return <div className="mb-3 flex flex-wrap items-center gap-2">{children}</div>;
    return ctx.slot ? createPortal(children, ctx.slot) : null;
}

export const TITLE = PAGE_TITLE;
/** The sentence under a title: muted, 15 points darker in light so it reads as strongly as it does in dark. */
export const LEAD = 'text-[14px] leading-relaxed text-foreground/75 dark:text-foreground/60';

/**
 * `section` titles a section's own page with its label and purpose; a page
 * passes `purpose` when it has a live line to say instead ("2 running now"). A
 * thing's own page puts how it stands right under its name (`status`: a pill
 * and one more fact, its address or what it's for).
 */
export function PageHeader({
    section,
    title,
    purpose,
    crumbs,
    status,
    chips,
    actions,
    className,
}: {
    section?: SectionId;
    title?: ReactNode;
    purpose?: ReactNode;
    crumbs?: Crumb[];
    status?: ReactNode;
    chips?: ReactNode;
    actions?: ReactNode;
    className?: string;
}) {
    const ctx = useContext(ActionsSlot);
    const def = section ? sectionById(section) : null;
    const heading = title ?? def?.label;
    const line = purpose ?? (crumbs ? null : def?.purpose);
    return (
        <header className={cn('mb-8', className)}>
            {crumbs && (
                <nav aria-label="Breadcrumb" className="mb-1 flex min-w-0 flex-wrap items-center gap-1 text-[13px] text-muted-foreground">
                    {crumbs.map((crumb, i) => (
                        <span key={i} className="inline-flex min-w-0 items-center gap-1">
                            {crumb.href ? (
                                <Link to={crumb.href} className="truncate rounded-sm transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                                    {crumb.label}
                                </Link>
                            ) : (
                                <span className="truncate">{crumb.label}</span>
                                )}
                                <ChevronRight aria-hidden className="h-3.5 w-3.5 shrink-0 opacity-60" />
                            </span>
                        ))}
                    </nav>
            )}
            {/* The actions sit on the title's row at every width, so a phone never gives them a row of their own. */}
            <div className="flex items-start justify-between gap-4">
                <h1 className={cn('m-0 min-w-0 break-words', TITLE)}>{heading}</h1>
                <div ref={ctx?.setSlot} className="flex shrink-0 flex-wrap items-center justify-end gap-2 empty:hidden">
                    {actions}
                </div>
            </div>
            {status && <div className="mt-1.5 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-[13px] text-muted-foreground">{status}</div>}
            {line && <p className={cn('m-0 mt-1.5 max-w-3xl', LEAD)}>{line}</p>}
            {chips && <div className="mt-2.5 flex flex-wrap items-center gap-2">{chips}</div>}
        </header>
    );
}

/** A `key: value` chip under a detail title; the value is an API name, so it reads as code. */
export function HeaderChip({ label, children }: { label: string; children: ReactNode }) {
    return (
        <span className="inline-flex max-w-full items-center gap-1 rounded-full bg-foreground/[0.05] px-2.5 py-0.5 text-[12px] text-muted-foreground">
            {label}:<span className="truncate font-mono text-foreground/85">{children}</span>
        </span>
    );
}

/**
 * A section of a page: a sentence-case heading with an optional count, an
 * optional link or action on the right, an optional note, then the body. No
 * box: sections are separated by space, rows by hairlines.
 */
export function PageSection({
    title,
    count,
    right,
    note,
    children,
    className,
    id,
}: {
    title: ReactNode;
    count?: number | null;
    right?: ReactNode;
    note?: ReactNode;
    children: ReactNode;
    className?: string;
    id?: string;
}) {
    return (
        <section id={id} aria-label={typeof title === 'string' ? title : undefined} className={cn('mt-12 first:mt-0', className)}>
            <div className="mb-3 flex min-h-8 items-center justify-between gap-3">
                <h2 className="m-0 flex items-baseline gap-2 text-[16px] font-semibold tracking-[-0.01em] text-foreground">
                    {title}
                    {count != null && count > 0 && <span className="text-[14px] font-normal tabular-nums text-muted-foreground">{count}</span>}
                </h2>
                {right && <div className="flex shrink-0 items-center gap-2">{right}</div>}
            </div>
            {note && <p className="m-0 -mt-1 mb-4 max-w-3xl text-[13px] leading-relaxed text-muted-foreground">{note}</p>}
            {children}
        </section>
    );
}
