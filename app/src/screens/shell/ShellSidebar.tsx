// The app's one navigation, as the frame (AppShell) draws it: the workspace and search atop it, then the pages, and at
// the foot what the host keeps there (a card, a balance) and the account with its menu. On a laptop it is a column that
// folds to an icon rail; on a phone the same content is the menu's sheet. What's the host's own fills the shell's slots
// (slots.ts); the host says which page is open and how to go to one.
import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router';
import { FaDiscord } from 'react-icons/fa6';
import { ChevronRight } from 'lucide-react';
import { useSlot } from '@/slots';
import { KINDS, type KindId } from '@/screens/resources/kinds';
import { AccountMenuBody } from '@/ui/AccountMenuBody';
import { ACCOUNT_MENU_ITEM, planLabel, type AccountMenuUser } from '@/ui/accountParts';
import { DropdownMenu, DropdownMenuItem, DropdownMenuTrigger } from '@/ui/dropdown-menu';
import { BuilderMark } from '@/ui/glyphs';
import { HAIRLINE } from '@/ui/primitives';
import { SIDEBAR_CURRENT, SidebarAccountButton, SidebarHeader, SidebarItem, useSidebarScale } from '@/ui/sidebarParts';
import { cn } from '@/ui/utils';
import type { SidebarFrame } from './AppShell';
import { SHELL_PAGES, type ShellPage } from './pages';
import { ACCOUNT_AROUND, ACCOUNT_BILLING, ACCOUNT_ITEMS, ACCOUNT_SESSION, ACCOUNT_STAFF, ACCOUNT_SWITCH, FOOT_BALANCE, FOOT_CARD, FOOT_INVITE, PAGES, WORKSPACE } from './slots';

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
 *  chevron only shows which). The choice is remembered. The kind open is the address's `kind`. */
export function ResourcesNav({
    page,
    current,
    collapsed,
    onKind,
    onNavigate,
}: {
    page: ShellPage;
    current: boolean;
    collapsed: boolean;
    /** Goes to Resources' overview (null) or one kind's list. */
    onKind: (kind: KindId | null) => void;
    onNavigate?: () => void;
}) {
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
        onKind(kind);
        onNavigate?.();
    };
    const phone = useSidebarScale() === 'phone';
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
                <div className={cn('relative mt-0.5 flex flex-col gap-0.5', phone ? 'pl-10' : 'pl-8')} role="group" aria-label="Resource kinds">
                    <span aria-hidden className={cn('absolute bottom-1.5 top-1.5 w-px bg-foreground/15', phone ? 'left-[25.5px]' : 'left-[21.5px]')} />
                    {KINDS.map((kind) => {
                        const here = activeKind === kind.id;
                        return (
                            <button
                                key={kind.id}
                                type="button"
                                onClick={() => go(kind.id)}
                                aria-current={here ? 'page' : undefined}
                                className={cn(
                                    'flex w-full items-center gap-2 text-left transition-colors',
                                    phone ? 'h-11 rounded-2xl px-3.5 text-[16px]' : 'h-9 rounded-xl px-3 text-[14.5px]',
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

const COMMUNITY = 'https://discord.com/invite/sHC2mrnss8';

/** The account at the sidebar's foot and its menu: who you are and your plan, the other place you work, the host's
 *  billing rows, its own rows, Community, its staff's rows, the theme and signing out. */
export function ShellAccount({ user, collapsed, go }: { user: AccountMenuUser; collapsed: boolean; go: (page: string) => void }) {
    const session = useSlot(ACCOUNT_SESSION);
    const plan = session.usePlan();
    const signOut = session.useSignOut();
    const switchTo = useSlot(ACCOUNT_SWITCH);
    const Billing = useSlot(ACCOUNT_BILLING);
    const Items = useSlot(ACCOUNT_ITEMS);
    const Staff = useSlot(ACCOUNT_STAFF);
    const Around = useSlot(ACCOUNT_AROUND);
    const row = (
        <div className={cn('flex items-center', collapsed && 'justify-center')}>
            <DropdownMenu>
                <DropdownMenuTrigger asChild>
                    <SidebarAccountButton user={user} plan={planLabel(plan)} collapsed={collapsed} data-onboarding="user-menu" />
                </DropdownMenuTrigger>
                <AccountMenuBody
                    user={user}
                    plan={plan}
                    onLogout={signOut}
                    billing={Billing ? <Billing /> : undefined}
                    switchTo={switchTo ?? undefined}
                    side={collapsed ? 'right' : 'top'}
                    align={collapsed ? 'end' : 'start'}
                >
                    {Items && <Items />}
                    <DropdownMenuItem className={ACCOUNT_MENU_ITEM} onClick={() => window.open(COMMUNITY, '_blank', 'noopener')}>
                        <FaDiscord className="mr-2 h-4 w-4 text-muted-foreground" />
                        <span>Community</span>
                    </DropdownMenuItem>
                    {Staff && <Staff go={go} />}
                </AccountMenuBody>
            </DropdownMenu>
        </div>
    );
    return Around ? <Around>{row}</Around> : row;
}

export interface ShellSidebarProps extends SidebarFrame {
    user: AccountMenuUser;
    onSearch: () => void;
    /** With a canvas open: the builder chat beside it, and its toggle. */
    builder?: { open: boolean; onToggle: () => void };
    /** The page open now. */
    current: string;
    /** Goes to a page: one of the shell's, or one of the host's own (its staff's). */
    onPage: (page: string) => void;
    /** Goes to Resources' overview (null) or one kind's list. */
    onKind: (kind: KindId | null) => void;
}

/** The sidebar's content, for the laptop column and the phone sheet alike: the pages this app serves, and what the
 *  host keeps in the slots (slots.ts) atop it and at its foot. */
export function ShellSidebarContent({ user, collapsed, headerEnd, onNavigate, onSearch, builder, current, onPage, onKind }: ShellSidebarProps) {
    const served = useSlot(PAGES);
    const Workspace = useSlot(WORKSPACE);
    const Card = useSlot(FOOT_CARD);
    const Balance = useSlot(FOOT_BALANCE);
    const Invite = useSlot(FOOT_INVITE);
    const pages = SHELL_PAGES.filter((page) => served.includes(page.id));
    const go = (page: string) => {
        onPage(page);
        onNavigate?.();
    };
    const search = () => {
        onNavigate?.();
        onSearch();
    };
    const phone = useSidebarScale() === 'phone';
    return (
        <div className="flex h-full min-h-0 flex-col">
            <SidebarHeader collapsed={collapsed} title={<Workspace user={user} onNavigate={onNavigate} />} onSearch={search} end={headerEnd} />

            <div className={cn('flex min-h-0 flex-1 flex-col overflow-y-auto pb-3 scrollbar-subtle', phone ? 'px-3 pt-1' : 'px-2')}>
                {builder && (
                    <div className={cn('mb-2 border-b pb-2', HAIRLINE)}>
                        <SidebarItem label="Builder" icon={BuilderMark} current={builder.open} collapsed={collapsed} onSelect={builder.onToggle} />
                    </div>
                )}
                <nav aria-label="Main" className="flex flex-col gap-0.5">
                    {pages.map((page) =>
                        page.id === 'resources' ? (
                            <ResourcesNav key={page.id} page={page} current={current === page.id} collapsed={collapsed} onKind={onKind} onNavigate={onNavigate} />
                        ) : (
                            <SidebarItem key={page.id} label={page.label} icon={page.icon} current={current === page.id} collapsed={collapsed} onSelect={() => go(page.id)} />
                        )
                    )}
                </nav>
            </div>

            {/* No rule above the foot: its card and account stand on the column's own surface. */}
            <div className={cn('flex shrink-0 flex-col', phone ? 'gap-2 px-3 pb-2' : 'gap-0.5 p-2')}>
                {!collapsed && Card && <Card />}
                {/* Mounted even on the rail: what's in it may listen for the app's events (a balance opens its way to
                    add funds when work runs out of them). */}
                {Balance && (
                    <div className={cn(collapsed && 'hidden')} data-onboarding="balance">
                        <Balance />
                    </div>
                )}
                {!collapsed && Invite && <Invite />}
                <ShellAccount user={user} collapsed={collapsed} go={go} />
            </div>
        </div>
    );
}
