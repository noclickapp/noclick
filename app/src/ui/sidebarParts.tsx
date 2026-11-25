// The sidebar's parts (rows, header, column, account button, the phone sheet's
// styling), shared by the app's sidebar and the developer console's so the two
// read as one app. They read no app state; each sidebar adds its own pages,
// workspace and account menu.
import { forwardRef, useEffect, type ButtonHTMLAttributes, type ComponentType, type ReactNode } from 'react';
import { Link } from 'react-router';
import { ArrowUpRight, PanelLeft, PanelLeftClose, Search, X } from 'lucide-react';
import { CountBadge } from '@/ui/CountBadge';
import { AccountAvatar, type AccountMenuUser } from '@/ui/accountParts';
import { LogoMark } from '@/ui/LogoMark';
import { ShortcutTooltip } from '@/ui/ShortcutTooltip';
import { HAIRLINE } from '@/ui/surfaces';
import { isTextEntryTarget } from '@/lib/keyboard';
import { userDisplayName } from '@/lib/userDisplay';
import { cn } from '@/ui/utils';
import { ResizeEdge } from '@/ui/ResizeEdge';
import { SIDEBAR_RAIL_WIDTH, sidebarPanel, useSidebarResizing, useSidebarWidth } from '@/ui/sidebarPanel';

// Every sidebar's rows (the app's and the developer console's) share these.
export const SIDEBAR_ITEM =
    'relative flex h-10 w-full items-center gap-3 rounded-xl px-3 text-[15px] tracking-[-0.005em] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';
export const SIDEBAR_IDLE = 'text-foreground/85 hover:bg-foreground/[0.05] hover:text-foreground dark:text-foreground/80';
export const SIDEBAR_CURRENT = 'bg-accent text-accent-foreground dark:bg-foreground/[0.09] dark:text-foreground';
export const SIDEBAR_ICON_BUTTON =
    "relative inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-xl after:absolute after:-inset-0.5 after:content-[''] text-foreground/75 transition-colors hover:bg-foreground/[0.05] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";
/** The phone's sidebar drawer and the dim behind it, shut or open by `data-open`; a swipe moves them in between
 *  (screens/shell/PhoneDrawer). Invisible while shut, so its shadow never shows at the screen's edge. */
export const SIDEBAR_SHEET =
    'fixed inset-y-0 left-0 z-[70] w-[300px] max-w-[85vw] border-r border-border bg-card pb-[env(safe-area-inset-bottom)] pt-[env(safe-area-inset-top)] shadow-2xl outline-none will-change-transform invisible -translate-x-full transition-[transform,visibility] duration-300 ease-[cubic-bezier(0.2,0.9,0.3,1)] data-[open=true]:visible data-[open=true]:translate-x-0 motion-reduce:transition-none dark:border-foreground/[0.08] dark:bg-black';
export const SIDEBAR_SHEET_OVERLAY =
    'pointer-events-none fixed inset-0 z-[60] bg-black/40 opacity-0 transition-opacity duration-300 ease-[cubic-bezier(0.2,0.9,0.3,1)] data-[open=true]:pointer-events-auto data-[open=true]:opacity-100 motion-reduce:transition-none';

export type SidebarIcon = ComponentType<{ className?: string; strokeWidth?: number }>;

/**
 * One sidebar row: a page (`onSelect`), a route (`to`) or a page elsewhere
 * (`href`, in a new tab). On the rail it is the icon alone, named by a tooltip.
 */
export function SidebarItem({
    label,
    icon: Icon,
    current = false,
    collapsed,
    onSelect,
    to,
    href,
    badge,
    trailing,
    expanded,
}: {
    label: string;
    icon: SidebarIcon;
    current?: boolean;
    collapsed: boolean;
    onSelect?: () => void;
    to?: string;
    href?: string;
    badge?: number;
    /** Drawn at the row's end, part of the row (a disclosure's chevron). */
    trailing?: ReactNode;
    /** For a row that also folds rows under it. */
    expanded?: boolean;
}) {
    const props = {
        onClick: onSelect,
        'aria-current': current ? ('page' as const) : undefined,
        'aria-expanded': expanded,
        'aria-label': collapsed ? label : undefined,
        className: cn(SIDEBAR_ITEM, current ? SIDEBAR_CURRENT : SIDEBAR_IDLE, collapsed && 'justify-center px-0'),
    };
    const body = (
        <>
            <Icon className="h-5 w-5 shrink-0" strokeWidth={1.6} />
            {!collapsed && <span className="min-w-0 flex-1 truncate text-left">{label}</span>}
            {!collapsed && href && <ArrowUpRight className="h-4 w-4 shrink-0 text-muted-foreground" strokeWidth={1.6} />}
            {!collapsed && trailing}
            {badge ? (
                <span className={cn(collapsed && 'absolute -right-1 -top-1 origin-top-right scale-[0.8]')}>
                    <CountBadge count={badge} />
                </span>
            ) : null}
        </>
    );
    const item = to ? (
        <Link to={to} {...props}>
            {body}
        </Link>
    ) : href ? (
        <a href={href} target="_blank" rel="noreferrer" {...props}>
            {body}
        </a>
    ) : (
        <button type="button" {...props}>
            {body}
        </button>
    );
    return collapsed ? (
        <ShortcutTooltip label={label} side="right">
            {item}
        </ShortcutTooltip>
    ) : (
        item
    );
}

/** Search as a round button, where a bar has no room for the field (the console's phone bar). */
export function SidebarSearch({ onSearch }: { onSearch: () => void }) {
    return (
        <ShortcutTooltip label="Search" keys={['mod', 'K']} sequence={false}>
            <button type="button" className={SIDEBAR_ICON_BUTTON} aria-label="Search" onClick={onSearch}>
                <Search className="h-5 w-5" strokeWidth={1.6} />
            </button>
        </ShortcutTooltip>
    );
}

/** Search as a field under the header, so the header row keeps its width for the workspace. */
function SidebarSearchField({ onSearch }: { onSearch: () => void }) {
    return (
        <button
            type="button"
            aria-label="Search"
            onClick={onSearch}
            className="flex h-9 w-full items-center gap-2.5 rounded-xl border border-border px-3 text-[14px] text-muted-foreground transition-colors hover:bg-foreground/[0.04] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring dark:border-foreground/[0.1]"
        >
            <Search className="h-4 w-4 shrink-0" strokeWidth={1.8} />
            <span className="flex-1 text-left">Search</span>
        </button>
    );
}

/** The header: the title and `end` (collapse on a laptop, close on a phone), search under them; on the rail, `end` alone. */
export function SidebarHeader({ collapsed, title, onSearch, end }: { collapsed: boolean; title: ReactNode; onSearch: () => void; end: ReactNode }) {
    if (collapsed) return <div className="flex h-14 shrink-0 items-center justify-center px-2">{end}</div>;
    return (
        <div className="shrink-0 px-2 pb-2">
            <div className="flex h-14 items-center gap-0.5">
                <div className="min-w-0 flex-1">{title}</div>
                {end}
            </div>
            <SidebarSearchField onSearch={onSearch} />
        </div>
    );
}

/** Folds the laptop column to its rail and back; ⌘\ does the same (`useSidebarShortcut`). */
export function SidebarToggle({ collapsed, onCollapsedChange }: { collapsed: boolean; onCollapsedChange: (collapsed: boolean) => void }) {
    return collapsed ? (
        <ShortcutTooltip label="Open sidebar" keys={['mod', '\\']} sequence={false} side="right">
            <button type="button" className={cn(SIDEBAR_ICON_BUTTON, 'group h-9 w-9')} aria-label="Open sidebar" onClick={() => onCollapsedChange(false)}>
                <LogoMark className="h-5 w-5 group-hover:hidden group-focus-visible:hidden" alt="" />
                <PanelLeft className="hidden h-5 w-5 group-hover:block group-focus-visible:block" strokeWidth={1.6} />
            </button>
        </ShortcutTooltip>
    ) : (
        <ShortcutTooltip label="Close sidebar" keys={['mod', '\\']} sequence={false}>
            <button type="button" className={SIDEBAR_ICON_BUTTON} aria-label="Close sidebar" onClick={() => onCollapsedChange(true)}>
                <PanelLeftClose className="h-5 w-5" strokeWidth={1.6} />
            </button>
        </ShortcutTooltip>
    );
}

/** ⌘\ opens and closes the sidebar, as in most sidebar apps. */
export function useSidebarShortcut(collapsed: boolean, onCollapsedChange: (collapsed: boolean) => void) {
    useEffect(() => {
        const onKey = (e: KeyboardEvent) => {
            if ((e.metaKey || e.ctrlKey) && e.key === '\\' && !isTextEntryTarget(e.target)) {
                e.preventDefault();
                onCollapsedChange(!collapsed);
            }
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [collapsed, onCollapsedChange]);
}

/** Who is signed in and their plan: the account menu's trigger at the sidebar's foot. */
export const SidebarAccountButton = forwardRef<
    HTMLButtonElement,
    { user: AccountMenuUser; plan: string; collapsed: boolean } & ButtonHTMLAttributes<HTMLButtonElement>
>(function SidebarAccountButton({ user, plan, collapsed, className, ...props }, ref) {
    return (
        <button
            ref={ref}
            type="button"
            aria-label={collapsed ? 'Account' : undefined}
            className={cn(
                'flex min-w-0 flex-1 items-center gap-2.5 rounded-lg p-1.5 text-left transition-colors hover:bg-foreground/[0.05] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring data-[state=open]:bg-foreground/[0.05]',
                collapsed && 'flex-none justify-center',
                className
            )}
            {...props}
        >
            <AccountAvatar user={user} className="h-8 w-8 shrink-0" />
            {!collapsed && (
                <span className="flex min-w-0 flex-col leading-tight">
                    <span className="truncate text-[13.5px] font-medium text-foreground">{userDisplayName({ email: user.email, name: user.display_name }, 'You')}</span>
                    <span className="truncate text-[12px] text-muted-foreground">{plan}</span>
                </span>
            )}
        </button>
    );
});

/** A laptop sidebar column: the width dragged from its edge (one width for every sidebar), or the rail. */
export function SidebarColumn({ collapsed, className, children, testId }: { collapsed: boolean; className?: string; children: ReactNode; testId?: string }) {
    const width = useSidebarWidth();
    const resizing = useSidebarResizing();
    return (
        <aside
            className={cn('border-r bg-card dark:bg-black', !resizing && 'transition-[width] duration-200 ease-[cubic-bezier(0.16,1,0.3,1)]', HAIRLINE, className)}
            style={{ width: collapsed ? SIDEBAR_RAIL_WIDTH : width }}
            data-testid={testId}
        >
            {!collapsed && <ResizeEdge panel={sidebarPanel} label="Resize sidebar" />}
            <div className="h-full overflow-hidden">{children}</div>
        </aside>
    );
}

/** The phone sheet's close control. */
export function SheetClose({ onClose }: { onClose: () => void }) {
    return (
        <button type="button" className={SIDEBAR_ICON_BUTTON} aria-label="Close menu" onClick={onClose}>
            <X className="h-5 w-5" strokeWidth={1.6} />
        </button>
    );
}
