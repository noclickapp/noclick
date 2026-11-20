// The app's pages in the shell's frame (AppShell): the account's home, the chat, Work and Resources, each a route of
// its own, with the sidebar listing the pages the app serves, the ⌘K palette, and on a phone the bar a page puts its
// actions and its way back in. The sidebar goes to a page by its route. The account is the one the app's key acts in,
// as `GET /v1/status` names it. The developer console keeps a frame of its own (screens/console/ConsoleShell.tsx),
// reached from the account menu.
import type { ReactNode } from 'react';
import { useLocation, useNavigate } from 'react-router';
import { readAccountStatus } from '@/screens/account/status';
import { useClient } from '@/sdk/client';
import { useV1 } from '@/sdk/useV1';
import type { AccountMenuUser } from '@/ui/accountParts';
import { useSidebarCollapsed } from '@/ui/sidebarPanel';
import { useIsMobile } from '@/ui/useIsMobile';
import { AppShell } from './AppShell';
import { shellPageFor } from './pages';
import { CommandPalette } from './palette/CommandPalette';
import { openCommandPalette } from './palette/open';
import { ShellSidebarContent } from './ShellSidebar';
import { kindRoute, pageRoute } from './slotStandards';

/** Where a phone's layout starts, as in NoClick's own app. */
const PHONE_BELOW = 769;

/** The page an address is on: one of the shell's, or none (the home). */
function pageAt(pathname: string): string {
    const first = pathname.split('/')[1] ?? '';
    return shellPageFor(first) ? first : '';
}

/** The phone bar's name for a page. The chat goes unnamed, as on a laptop: it is the app itself. */
function titleOf(page: string): string {
    if (page === 'chat') return '';
    return shellPageFor(page)?.label ?? 'NoClick';
}

export function AppFrame({ children }: { children: ReactNode }) {
    const isMobile = useIsMobile(PHONE_BELOW);
    const [collapsed, setCollapsed] = useSidebarCollapsed();
    const navigate = useNavigate();
    const page = pageAt(useLocation().pathname);
    const client = useClient();
    const account = useV1('status', (signal) => readAccountStatus(client, signal), { client }).data?.account;
    const user: AccountMenuUser = { email: account?.email ?? '', display_name: account?.name ?? undefined };
    return (
        <>
            <CommandPalette />
            <AppShell
                isMobile={isMobile}
                sidebar={(frame) => (
                    <ShellSidebarContent
                        {...frame}
                        user={user}
                        onSearch={() => openCommandPalette()}
                        current={page}
                        onPage={(id) => navigate(pageRoute(id))}
                        onKind={(kind) => navigate(kind ? kindRoute(kind) : pageRoute('resources'))}
                    />
                )}
                collapsed={collapsed}
                onCollapsedChange={setCollapsed}
                title={titleOf(page)}
                builder={null}
                builderShown={false}
                builderWidth={0}
                animate
            >
                {children}
            </AppShell>
        </>
    );
}
