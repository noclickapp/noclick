// The console's one navigation, built from the sidebar's shared parts so a host
// app and its console read as one product: the same rows, header, width, rail
// and account. What the host put atop it and search on top, then a back row to
// the app (as Vercel's settings open), Home and the sections in their groups
// (Build, Watch, Access, labelled as Settings labels its own), Docs and Settings
// at the foot, then your account. No counts: the console builds and watches,
// and nothing in it waits on you.
import type { ReactNode } from 'react';
import { BookOpen, ChevronLeft } from 'lucide-react';
import { Link } from 'react-router';
import { DropdownMenu, DropdownMenuTrigger } from '@/ui/dropdown-menu';
import { AccountMenuBody } from '@/ui/AccountMenuBody';
import { planLabel } from '@/ui/accountParts';
import { SIDEBAR_ITEM, SidebarAccountButton, SidebarHeader, SidebarItem } from '@/ui/sidebarParts';
import { cn } from '@/ui/utils';
import { useAccountPlan, useConsole, useConsoleHref } from '@/screens/console/hooks/useConsole';
import { docsUrl } from '@/screens/console/lib/site';
import { openConsolePalette } from './ConsolePalette';
import { useOwnerOnly } from './ownerOnly';
import { listedSections, SECTION_GROUPS, type SectionDef, type SectionId } from './sections';

/** Where you are, and the way back to the app: the chevron at the row's start, the console's name in its middle. */
function BackToApp({ collapsed, onNavigate }: { collapsed: boolean; onNavigate?: () => void }) {
    const { home } = useConsole();
    if (collapsed) return <SidebarItem label="Back to NoClick" icon={ChevronLeft} to={home} collapsed onSelect={onNavigate} />;
    return (
        <Link to={home} onClick={onNavigate} aria-label="Back to NoClick from Developers" className={cn(SIDEBAR_ITEM, 'group justify-center text-muted-foreground hover:bg-foreground/[0.05] hover:text-foreground')}>
            <ChevronLeft className="absolute left-3 h-5 w-5 transition-transform duration-150 group-hover:-translate-x-0.5" strokeWidth={1.6} />
            <span className="font-medium">Developers</span>
        </Link>
    );
}

function Account({ collapsed }: { collapsed: boolean }) {
    const { user, signOut } = useConsole();
    const plan = useAccountPlan() ?? null;
    const account = { email: user.email ?? '' };
    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <SidebarAccountButton user={account} plan={plan ? planLabel(plan) : ''} collapsed={collapsed} />
            </DropdownMenuTrigger>
            <AccountMenuBody user={account} plan={plan} onLogout={signOut} side={collapsed ? 'right' : 'top'} align={collapsed ? 'end' : 'start'} />
        </DropdownMenu>
    );
}

/** The sidebar's content, shared by the laptop column and the phone sheet. */
export function ConsoleSidebarContent({
    active,
    collapsed,
    headerEnd,
    onNavigate,
}: {
    active: SectionId | null;
    collapsed: boolean;
    /** The header's closing control (collapse on a laptop, close on a phone). */
    headerEnd: ReactNode;
    /** Called after any navigation, so a sheet can close itself. */
    onNavigate?: () => void;
}) {
    const href = useConsoleHref();
    const { workspace, site } = useConsole();
    const listed = listedSections(useOwnerOnly());
    const item = (s: SectionDef) => (
        <SidebarItem key={s.id} label={s.label} icon={s.icon} to={href(s.id === 'home' ? '' : s.id)} current={s.id === active} collapsed={collapsed} onSelect={onNavigate} />
    );
    const main = listed.filter((s) => !s.footer);
    return (
        <div className="flex h-full min-h-0 flex-col">
            <SidebarHeader
                collapsed={collapsed}
                title={workspace}
                onSearch={() => {
                    onNavigate?.();
                    openConsolePalette();
                }}
                end={headerEnd}
            />
            <div className="flex min-h-0 flex-1 flex-col overflow-y-auto px-2 pb-3 scrollbar-subtle">
                <div className="mb-1">
                    <BackToApp collapsed={collapsed} onNavigate={onNavigate} />
                </div>
                <nav aria-label="Developer console" className="flex flex-col gap-0.5">
                    {main.filter((s) => !s.group).map(item)}
                    {SECTION_GROUPS.map((group) => {
                        const items = main.filter((s) => s.group === group);
                        if (!items.length) return null;
                        return (
                            <div key={group} role="group" aria-label={group} className="mt-4 flex flex-col gap-0.5">
                                {/* Labelled as Settings labels its groups; folded to a rail, the gap alone sets them apart. */}
                                {!collapsed && <p className="m-0 px-3 pb-1 text-[12.5px] font-medium text-muted-foreground">{group}</p>}
                                {items.map(item)}
                            </div>
                        );
                    })}
                </nav>
                <div className="flex-1" />
                <div className="flex flex-col gap-0.5 pt-3">
                    <SidebarItem label="Docs" icon={BookOpen} href={docsUrl(site)} collapsed={collapsed} />
                    {listed.filter((s) => s.footer).map(item)}
                </div>
            </div>
            <div className={cn('flex shrink-0 items-center p-2', collapsed && 'justify-center')}>
                <Account collapsed={collapsed} />
            </div>
        </div>
    );
}
