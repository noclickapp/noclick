// The frame around the signed-in owner's pages (src/screens/shell/AppFrame.tsx): the home, the chat, Work,
// Connections, Resources and Usage draw inside it, each its own route below, and the sidebar goes to a page by its
// route (Usage is opened from the account menu, and a phone's bar names it all the same). The account is the
// one the app's key acts in, as `GET /v1/status` names it. The developer console, reached from the account menu, draws
// the same frame with its own sidebar (src/screens/console/ConsoleShell.tsx). The frame reads nothing on the server, so
// moving between the pages never waits on it.
import { Outlet, useLocation, useNavigate } from 'react-router';
import { readAccountStatus } from '@/screens/account/status';
import { AppFrame } from '@/screens/shell/AppFrame';
import { shellPageFor, shellPageTitle } from '@/screens/shell/pages';
import { kindRoute, pageRoute } from '@/screens/shell/slotStandards';
import { useClient } from '@/sdk/client';
import { useV1 } from '@/sdk/useV1';
import type { AccountMenuUser } from '@/ui/accountParts';
import { useSidebarCollapsed } from '@/ui/sidebarPanel';
import { useIsMobile } from '@/ui/useIsMobile';

/** Where a phone's layout starts, as in NoClick's own app. */
const PHONE_BELOW = 769;

export const shouldRevalidate = () => false;

/** The app's own pages that aren't the shell's (the sidebar doesn't list them), by their route, named as the shell
 *  names its pages in a phone's bar. */
const OWN_PAGES: Readonly<Record<string, string>> = { usage: 'Usage' };

/** The first segment of an address: the page's route. */
const routeOf = (pathname: string) => pathname.split('/')[1] ?? '';

/** The page an address is on: one of the shell's, or none (the home, or one of the app's own). */
function pageAt(pathname: string): string {
    const first = routeOf(pathname);
    return shellPageFor(first) ? first : '';
}

export default function Shell() {
    const isMobile = useIsMobile(PHONE_BELOW);
    const [collapsed, setCollapsed] = useSidebarCollapsed();
    const navigate = useNavigate();
    const { pathname } = useLocation();
    const page = pageAt(pathname);
    const client = useClient();
    const account = useV1('status', (signal) => readAccountStatus(client, signal), { client }).data?.account;
    const user: AccountMenuUser = { email: account?.email ?? '', display_name: account?.name ?? undefined };
    return (
        <AppFrame
            isMobile={isMobile}
            user={user}
            places={{ current: page, go: (id) => navigate(pageRoute(id)), goKind: (kind) => navigate(kind ? kindRoute(kind) : pageRoute('resources')) }}
            collapsed={collapsed}
            onCollapsedChange={setCollapsed}
            title={OWN_PAGES[routeOf(pathname)] ?? shellPageTitle(page)}
            builder={null}
            builderShown={false}
            builderWidth={0}
            animate
        >
            <Outlet />
        </AppFrame>
    );
}
