// The app's one navigation: the workspace, search, the pages, and at the foot
// a prompt to text NoClick (until a phone is linked), your balance and account. On a laptop it is a
// fixed column that collapses to an icon rail (and does so by itself while a
// workflow canvas is open, so the builder chat and canvas get the width); on a
// phone the same content opens as a sheet. Its parts (rows, header, column,
// account button) are exported for the developer console's sidebar, so the two
// read as one app.
import { forwardRef, useEffect, useState, type ButtonHTMLAttributes, type ComponentType, type ReactNode } from 'react';
import { Link, useSearchParams } from 'react-router';
import { FaDiscord } from 'react-icons/fa6';
import { ArrowUpRight, Bug, ChartLine, ChevronRight, PanelLeft, PanelLeftClose, Search, X } from 'lucide-react';
import { DropdownMenu, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '~/components/ui/dropdown-menu';
import { FeedbackButton } from '~/components/nav/FeedbackButton';
import { CountBadge } from '~/components/nav/CountBadge';
import { ACCOUNT_MENU_ITEM, AccountAvatar, AccountMenuContent, planLabel, useAccountPlan, type AccountMenuSwitch, type AccountMenuUser } from '~/components/nav/AccountMenu';
import { OrgSwitcher } from '~/components/organization/OrgSwitcher';
import { LogoMark } from '~/components/shared/LogoMark';
import { ShortcutTooltip } from '~/components/shared/ShortcutTooltip';
import { KeyHint } from '~/components/shared/KeyHint';
import { HAIRLINE } from '~/components/dashboard/primitives';
import { useDebugToolsEnabled } from '~/hooks/useDebugToolsEnabled';
import { isTextEntryTarget } from '~/lib/keyboard';
import { navigateToTab } from '~/lib/navigation';
import { openCommandPalette } from '~/lib/shortcuts';
import { userDisplayName } from '~/lib/userDisplay';
import { cn } from '~/lib/utils';
import { SHELL_PAGES, type ShellPage } from './pages';
import { visibleKinds, type KindId } from './resources/kinds';
import { hasPlatformResources } from './resources/platform';
import { BuilderMark } from './glyphs';
import { MENU_SEPARATOR } from './menus';
import { ResizeEdge } from './ResizeEdge';
import { TextNoClickBanner } from './TextNoClickBanner';
import { SIDEBAR_RAIL_WIDTH, sidebarPanel, useSidebarResizing, useSidebarWidth } from './sidebarWidth';


// Every sidebar's rows (the app's and the developer console's) share these.
export const SIDEBAR_ITEM =
    'relative flex h-10 w-full items-center gap-3 rounded-xl px-3 text-[15px] tracking-[-0.005em] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';
export const SIDEBAR_IDLE = 'text-foreground/85 hover:bg-foreground/[0.05] hover:text-foreground dark:text-foreground/80';
export const SIDEBAR_CURRENT = 'bg-accent text-accent-foreground dark:bg-foreground/[0.09] dark:text-foreground';
export const SIDEBAR_ICON_BUTTON =
    'inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-foreground/75 transition-colors hover:bg-foreground/[0.05] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';
/** The phone's sidebar sheet and the dim behind it. */
export const SIDEBAR_SHEET =
    'fixed inset-y-0 left-0 z-[70] w-[300px] max-w-[85vw] border-r border-border bg-card pt-[env(safe-area-inset-top)] shadow-2xl outline-none duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] data-[state=closed]:animate-out data-[state=open]:animate-in data-[state=closed]:slide-out-to-left data-[state=open]:slide-in-from-left dark:border-foreground/[0.08] dark:bg-black';
export const SIDEBAR_SHEET_OVERLAY =
    'fixed inset-0 z-[60] bg-black/40 data-[state=closed]:animate-out data-[state=open]:animate-in data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0';

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

/** Search as a field under the header, as Vercel's sidebar has it, so the header row keeps its width for the workspace. */
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
            <KeyHint keys={['mod', 'K']} />
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

const RESOURCES_OPEN_KEY = 'nc-sidebar-resources-open';

function storedOpen(): boolean {
    try {
        return window.localStorage.getItem(RESOURCES_OPEN_KEY) === '1';
    } catch {
        return false;
    }
}

/** Resources, with a row per kind under it: the page is an overview, a kind is its list. One row, as in
 *  Cloudflare's sidebar: it opens onto the overview, and clicked again while open it folds its kinds away (the
 *  chevron only shows which). The choice is remembered. */
export function ResourcesNav({ page, current, collapsed, onNavigate }: { page: ShellPage; current: boolean; collapsed: boolean; onNavigate?: () => void }) {
    const [params] = useSearchParams();
    const activeKind = current ? (params.get('kind') as KindId | null) : null;
    const [open, setOpen] = useState(false);
    useEffect(() => setOpen(storedOpen()), []);
    useEffect(() => {
        if (current) setOpen(true);
    }, [current]);
    const remember = (next: boolean) => {
        setOpen(next);
        try {
            window.localStorage.setItem(RESOURCES_OPEN_KEY, next ? '1' : '0');
        } catch {
            // Not remembered this time.
        }
    };
    const go = (kind: KindId | null) => {
        navigateToTab('resources', { kind, resource: null, path: null });
        onNavigate?.();
    };
    const select = () => {
        if (current && open) return remember(false);
        remember(true);
        go(null);
    };
    if (collapsed) return <SidebarItem label={page.label} icon={page.icon} current={current} collapsed onSelect={() => go(null)} />;
    return (
        <div>
            <SidebarItem
                label={page.label}
                icon={page.icon}
                current={current && (!activeKind || !open)}
                collapsed={false}
                onSelect={select}
                expanded={open}
                trailing={<ChevronRight className={cn('h-4 w-4 shrink-0 text-muted-foreground transition-transform duration-200', open && 'rotate-90')} strokeWidth={1.8} />}
            />
            {open && (
                // Text rows on a guide line hung from the Resources icon; each lines up with the parent's label.
                <div className="relative mt-0.5 flex flex-col gap-0.5 pl-8" role="group" aria-label="Resource kinds">
                    <span aria-hidden className="absolute bottom-1.5 left-[21.5px] top-1.5 w-px bg-foreground/15" />
                    {visibleKinds({ platform: hasPlatformResources() }).map((kind) => {
                        const here = activeKind === kind.id;
                        return (
                            <button
                                key={kind.id}
                                type="button"
                                onClick={() => go(kind.id)}
                                aria-current={here ? 'page' : undefined}
                                className={cn(
                                    'flex h-9 w-full items-center gap-2 rounded-xl px-3 text-left text-[14.5px] transition-colors',
                                    here ? SIDEBAR_CURRENT : 'text-foreground/75 hover:bg-foreground/[0.05] hover:text-foreground'
                                )}
                            >
                                <span className="min-w-0 truncate">{kind.label}</span>
                            </button>
                        );
                    })}
                </div>
            )}
        </div>
    );
}

/** The local backend a dev frontend talks to, for telling worktrees apart. */
function devBackendLabel(): string | null {
    const port = (import.meta.env.VITE_API_URL || '').match(/localhost:(\d+)/)?.[1];
    return import.meta.env.DEV && port ? `:${port}` : null;
}

function AccountRow({
    user,
    collapsed,
    billing,
    switchTo,
    onNavigate,
    onTabChange,
}: {
    user: AccountMenuUser;
    collapsed: boolean;
    billing?: ReactNode;
    switchTo?: AccountMenuSwitch;
    onNavigate?: () => void;
    onTabChange: (tab: string) => void;
}) {
    const plan = useAccountPlan();
    const internal = useDebugToolsEnabled();
    const dev = devBackendLabel();
    const go = (tab: string) => {
        onTabChange(tab);
        onNavigate?.();
    };
    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <SidebarAccountButton user={user} plan={planLabel(plan)} collapsed={collapsed} data-onboarding="user-menu" />
            </DropdownMenuTrigger>
            <AccountMenuContent
                user={user}
                billing={billing}
                switchTo={switchTo}
                side={collapsed ? 'right' : 'top'}
                align={collapsed ? 'end' : 'start'}
            >
                <DropdownMenuItem className={ACCOUNT_MENU_ITEM} onClick={() => window.open('https://discord.com/invite/sHC2mrnss8', '_blank', 'noopener')}>
                    <FaDiscord className="mr-2 h-4 w-4 text-muted-foreground" />
                    <span>Community</span>
                </DropdownMenuItem>
                {internal && (
                    <>
                        <DropdownMenuSeparator className={MENU_SEPARATOR} />
                        <DropdownMenuItem className={ACCOUNT_MENU_ITEM} onClick={() => go('debug')}>
                            <Bug className="mr-2 h-4 w-4 text-muted-foreground" />
                            <span>Debug</span>
                            {dev && <span className="ml-auto font-mono text-[11px] text-muted-foreground">{dev}</span>}
                        </DropdownMenuItem>
                        <DropdownMenuItem className={ACCOUNT_MENU_ITEM} onClick={() => go('analytics')}>
                            <ChartLine className="mr-2 h-4 w-4 text-muted-foreground" />
                            <span>Analytics</span>
                        </DropdownMenuItem>
                        <DropdownMenuSeparator className={MENU_SEPARATOR} />
                    </>
                )}
            </AccountMenuContent>
        </DropdownMenu>
    );
}

export interface SidebarProps {
    user: AccountMenuUser;
    selectedTab: string;
    onTabChange: (tab: string) => void;
    /** With a canvas open: the builder chat beside it, and its toggle. */
    builder?: { open: boolean; onToggle: () => void };
    /** What the host adds (hosted: the balance meter, the invite row under it and the billing rows). */
    slots?: { balance?: ReactNode; invite?: ReactNode; billing?: ReactNode };
    /** The other place this account works (hosted: the developer console), first in the account menu;
     *  the console keeps the way back in the same spot. */
    switchTo?: AccountMenuSwitch;
}

/** The sidebar's content, shared by the laptop column and the phone sheet. */
export function SidebarContent({
    user,
    selectedTab,
    onTabChange,
    builder,
    slots,
    switchTo,
    collapsed = false,
    headerEnd,
    onNavigate,
}: SidebarProps & {
    collapsed?: boolean;
    /** The header's closing control (collapse on a laptop, close on a phone). */
    headerEnd: ReactNode;
    /** Called after any navigation, so a sheet can close itself. */
    onNavigate?: () => void;
}) {
    const go = (tab: string) => {
        onTabChange(tab);
        onNavigate?.();
    };
    const search = () => {
        onNavigate?.();
        openCommandPalette();
    };
    return (
        <div className="flex h-full min-h-0 flex-col">
            <SidebarHeader
                collapsed={collapsed}
                title={<OrgSwitcher userEmail={user.email} userLabel={user.display_name} userAvatarUrl={user.avatar_url} variant="sidebar" />}
                onSearch={search}
                end={headerEnd}
            />

            <div className="flex min-h-0 flex-1 flex-col overflow-y-auto px-2 pb-3 scrollbar-subtle">
                {builder && (
                    <div className={cn('mb-2 border-b pb-2', HAIRLINE)}>
                        <SidebarItem label="Builder" icon={BuilderMark} current={builder.open} collapsed={collapsed} onSelect={builder.onToggle} />
                    </div>
                )}
                <nav aria-label="Main" className="flex flex-col gap-0.5">
                    {SHELL_PAGES.map((page) =>
                        page.id === 'resources' ? (
                            <ResourcesNav key={page.id} page={page} current={selectedTab === page.id} collapsed={collapsed} onNavigate={onNavigate} />
                        ) : (
                            <SidebarItem
                                key={page.id}
                                label={page.label}
                                icon={page.icon}
                                current={selectedTab === page.id}
                                collapsed={collapsed}
                                onSelect={() => go(page.id)}
                            />
                        )
                    )}
                </nav>
            </div>

            {/* The Text NoClick card is its own edge: no rule above it. */}
            <div className={cn('flex shrink-0 flex-col gap-0.5 border-t p-2 [&:has([data-testid=text-noclick-banner])]:border-t-0', HAIRLINE)}>
                {!collapsed && <TextNoClickBanner />}
                {/* Mounted even on the rail: the hosted balance owns the out-of-funds
                    listeners that open the top-up flow mid-run. */}
                {slots?.balance && (
                    <div className={cn(collapsed && 'hidden')} data-onboarding="balance">
                        {slots.balance}
                    </div>
                )}
                {!collapsed && slots?.invite}
                <FeedbackButton>
                    <div className={cn('flex items-center', collapsed && 'justify-center')}>
                        <AccountRow user={user} collapsed={collapsed} billing={slots?.billing} switchTo={switchTo} onNavigate={onNavigate} onTabChange={onTabChange} />
                    </div>
                </FeedbackButton>
            </div>
        </div>
    );
}

/** The laptop column: a resizable width, or a 56px rail. */
export function AppSidebar({ collapsed, onCollapsedChange, ...props }: SidebarProps & { collapsed: boolean; onCollapsedChange: (collapsed: boolean) => void }) {
    return (
        <SidebarColumn collapsed={collapsed} className="fixed inset-y-0 left-0 z-30" testId="app-sidebar">
            <SidebarContent {...props} collapsed={collapsed} headerEnd={<SidebarToggle collapsed={collapsed} onCollapsedChange={onCollapsedChange} />} />
        </SidebarColumn>
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
