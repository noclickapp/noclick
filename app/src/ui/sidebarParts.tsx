// The sidebar's parts (rows, header, column, account button, the phone drawer's
// styling), shared by the app's sidebar and the developer console's so the two
// read as one app. They read no app state; each sidebar adds its own pages,
// workspace and account menu.
import { createContext, forwardRef, useContext, useEffect, type ButtonHTMLAttributes, type ComponentType, type ReactNode } from 'react';
import { Link } from 'react-router';
import { ArrowUpRight, PanelLeft, PanelLeftClose, Search } from 'lucide-react';
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
/** A row you tap to go somewhere, as a phone's own lists behave: lit while pressed rather than left looking hovered
 *  (a hover style sticks to whatever a finger last touched), and no link preview on a long press. */
export const TAP_ROW = '[-webkit-touch-callout:none] [@media(hover:none)]:active:bg-foreground/[0.08]';
export const SIDEBAR_IDLE = `text-foreground/85 [@media(hover:hover)]:hover:bg-foreground/[0.05] [@media(hover:hover)]:hover:text-foreground dark:text-foreground/80 ${TAP_ROW}`;
export const SIDEBAR_CURRENT = 'bg-accent text-accent-foreground dark:bg-foreground/[0.09] dark:text-foreground';
export const SIDEBAR_ICON_BUTTON =
    "relative inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-xl after:absolute after:-inset-0.5 after:content-[''] text-foreground/75 transition-colors hover:bg-foreground/[0.05] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";
/** The phone's sidebar sits under the page, which slides right off it as a rounded, dimmed card (screens/shell/
 *  PhoneDrawer). Shut or open by `data-open`; a swipe moves them in between. Its width is `PHONE_DRAWER_WIDTH`, written
 *  out in each class (Tailwind reads class names as written). */
export const PHONE_DRAWER_WIDTH = 'min(80vw,340px)';
export const SIDEBAR_SHEET =
    'group/sheet fixed inset-y-0 left-0 z-0 w-[min(80vw,340px)] bg-background pb-[env(safe-area-inset-bottom)] pt-[env(safe-area-inset-top)] outline-none invisible -translate-x-[18%] transition-[transform,visibility] duration-300 ease-[cubic-bezier(0.2,0.9,0.3,1)] data-[open=true]:visible data-[open=true]:translate-x-0 motion-reduce:transition-none';
/** The page while the drawer is open: moved right by the drawer's width, its near corners rounded, over the drawer. */
export const PHONE_PAGE =
    'group/page z-[1] transition-[transform,border-radius] duration-300 ease-[cubic-bezier(0.2,0.9,0.3,1)] data-[menu=open]:translate-x-[min(80vw,340px)] data-[menu=open]:overflow-hidden data-[menu=open]:rounded-l-[44px] motion-reduce:transition-none';
/** Your picture at the bar's start, which opens the drawer: it fades off the page as the drawer opens, and the same
 *  picture fades in at the drawer's top (`PHONE_ME_IN_SHEET`), as X's does. A swipe sets both as it goes (PhoneDrawer,
 *  by `data-phone-me`). */
export const PHONE_ME_ON_PAGE =
    'transition-[opacity,transform] duration-300 ease-[cubic-bezier(0.2,0.9,0.3,1)] group-data-[menu=open]/page:scale-[0.85] group-data-[menu=open]/page:opacity-0 motion-reduce:transition-none';
export const PHONE_ME_IN_SHEET =
    'scale-[0.85] opacity-0 transition-[opacity,transform] duration-300 ease-[cubic-bezier(0.2,0.9,0.3,1)] group-data-[open=true]/sheet:scale-100 group-data-[open=true]/sheet:opacity-100 motion-reduce:transition-none';
/** The dim over the page while it's pushed aside: it greys the page out, a card you tap to come back to. */
export const SIDEBAR_SHEET_OVERLAY =
    'pointer-events-none absolute inset-0 z-[45] bg-black/[0.16] opacity-0 transition-opacity duration-300 ease-[cubic-bezier(0.2,0.9,0.3,1)] data-[open=true]:opacity-100 motion-reduce:transition-none dark:bg-[rgb(44_44_44/0.58)]';

/** How big a sidebar's parts are drawn: a laptop column's, or a phone drawer's, sized for a thumb (bigger rows, search
 *  as an icon beside the workspace). The phone drawer provides it. */
export type SidebarScale = 'column' | 'phone';
const SidebarScaleContext = createContext<SidebarScale>('column');
export const SidebarScaleProvider = SidebarScaleContext.Provider;
export function useSidebarScale(): SidebarScale {
    return useContext(SidebarScaleContext);
}
const PHONE_ITEM = 'h-12 gap-4 rounded-2xl px-3.5 text-[17px] tracking-[-0.01em]';

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
    const phone = useSidebarScale() === 'phone';
    const props = {
        onClick: onSelect,
        'aria-current': current ? ('page' as const) : undefined,
        'aria-expanded': expanded,
        'aria-label': collapsed ? label : undefined,
        className: cn(SIDEBAR_ITEM, phone && PHONE_ITEM, current ? SIDEBAR_CURRENT : SIDEBAR_IDLE, collapsed && 'justify-center px-0'),
    };
    const body = (
        <>
            <Icon className={cn('shrink-0', phone ? 'h-6 w-6' : 'h-5 w-5')} strokeWidth={1.6} />
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

/** The header: the title and `end` (collapse on a laptop), search under them; on the rail, `end` alone; in a phone's
 *  drawer, the title with search as an icon beside it, nothing to close (the page beside it closes it). */
export function SidebarHeader({ collapsed, title, onSearch, end }: { collapsed: boolean; title: ReactNode; onSearch: () => void; end: ReactNode }) {
    const phone = useSidebarScale() === 'phone';
    if (collapsed) return <div className="flex h-14 shrink-0 items-center justify-center px-2">{end}</div>;
    if (phone)
        return (
            <div className="flex h-16 shrink-0 items-center gap-1 px-3">
                <div className="min-w-0 flex-1">{title}</div>
                <button type="button" aria-label="Search" onClick={onSearch} className={cn(SIDEBAR_ICON_BUTTON, 'h-11 w-11 rounded-full')}>
                    <Search className="h-[22px] w-[22px]" strokeWidth={1.8} />
                </button>
                {end}
            </div>
        );
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
    const phone = useSidebarScale() === 'phone';
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
            <AccountAvatar user={user} className={cn('shrink-0', phone ? 'h-10 w-10' : 'h-8 w-8')} />
            {!collapsed && (
                <span className="flex min-w-0 flex-col leading-tight">
                    <span className={cn('truncate font-medium text-foreground', phone ? 'text-[16px]' : 'text-[13.5px]')}>{userDisplayName({ email: user.email, name: user.display_name }, 'You')}</span>
                    <span className={cn('truncate text-muted-foreground', phone ? 'text-[14px]' : 'text-[12px]')}>{plan}</span>
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
