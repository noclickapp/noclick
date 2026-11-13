// @vitest-environment happy-dom
// A person's first sign-in: the token the JWT hook mints for an account with no onboarding answers lands on the
// dashboard's Chat, through the real loader, route and Dashboard. Only the pages' contents and the account's live
// connections are stubbed.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { createRoutesStub } from 'react-router';
import DashboardRoute, { loader } from '~/routes/dashboard';

const USER = {
    id: 'new-user',
    email: 'new@example.com',
    created_at: '2026-11-13T10:00:00Z',
    user_metadata: {},
};
// What the hook mints before the account has any onboarding row.
const CLAIMS = { sub: USER.id, subscription_tier: 'free', onboarding_completed: false };
const TOKEN = `header.${Buffer.from(JSON.stringify(CLAIMS)).toString('base64')}.signature`;

vi.mock('~/lib/supabase', () => ({
    requireAuth: async () => ({
        user: USER,
        signedInUser: USER,
        viewing: null,
        session: { access_token: TOKEN },
        headers: new Headers(),
    }),
    signOut: async () => new Headers(),
    createBrowserSupabaseClient: () => ({ auth: { refreshSession: async () => ({ error: null }) } }),
}));
vi.mock('~/lib/session.server', () => ({ getSession: async () => ({ get: () => undefined }), commitSession: async () => '' }));
vi.mock('~/cloud/lib/subscription', () => ({ createPool: () => ({}) }));
vi.mock('~/cloud/lib/shopify-free-only.server', () => ({
    openShopifyAppStoreCheck: () => ({ check: async () => false, close: async () => {} }),
}));
vi.mock('~/lib/nodeCatalog.server', () => ({
    getAllSerializedNodeMeta: () => ({}),
    getNodeIconsFile: () => ({ version: 'test', body: '{}' }),
}));
// The page preloads the node-icon file it names, which no server here serves.
vi.mock('react-dom', async (importOriginal) => ({ ...(await importOriginal<typeof import('react-dom')>()), preload: () => {} }));
vi.mock('posthog-js', () => ({
    default: { identify: () => {}, capture: () => {}, has_opted_out_capturing: () => false, opt_in_capturing: () => {}, opt_out_capturing: () => {} },
}));
vi.mock('posthog-js/react', () => ({ useFeatureFlagEnabled: () => false }));

// The account's live connections.
vi.mock('~/hooks/useEventRelay', () => ({ useEventRelay: () => {} }));
vi.mock('~/components/debug/MimicUserView', () => ({ useMimicFollowsServer: () => {}, useViewedUserId: (id: string) => id }));
vi.mock('~/hooks/useSocketTokenRefresh', () => ({ useSocketTokenRefresh: () => {} }));
vi.mock('~/hooks/useMCPNavigation', () => ({ useMCPNavigation: () => {} }));
vi.mock('~/hooks/useShareNotifications', () => ({ useShareNotifications: () => {} }));
vi.mock('~/hooks/useTrackingSync', () => ({ useTrackingSync: () => {} }));
vi.mock('~/hooks/useCrispChat', () => ({ useCrispIdentity: () => {} }));
vi.mock('~/hooks/useApprovalCount', () => ({ useApprovalCount: () => {} }));
vi.mock('~/hooks/useOnboarding', () => ({ OnboardingProvider: ({ children }: { children: React.ReactNode }) => children }));
vi.mock('~/components/chat/drawer/ChatDrawerProvider', () => ({
    ChatDrawerProvider: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock('~/hooks/WorkflowBrowserDataProvider', () => ({
    WorkflowBrowserDataProvider: ({ children }: { children: React.ReactNode }) => children,
}));

// The shell around the page, and each page's contents: the chat says which page is showing.
// The open edition's Dashboard has a nav bar where the hosted one has the shell.
vi.mock('~/components/shell/AppShell', () => ({ AppShell: ({ children }: { children: React.ReactNode }) => children }));
vi.mock('~/components/nav/NavBar', () => ({ NavBar: () => null }));
vi.mock('~/components/shell/CoordinatorHome', () => ({ CoordinatorHome: () => <main>NoClick chat</main> }));
vi.mock('~/components/workflow/WorkflowBrowser', () => ({ WorkflowBrowser: () => <main>Automations</main> }));
vi.mock('~/components/shell/work', () => ({ WorkPage: () => null }));
vi.mock('~/components/shell/ResourcesPage', () => ({ ResourcesPage: () => null }));
vi.mock('~/components/shell/ConnectionsPage', () => ({ ConnectionsPage: () => null }));
vi.mock('~/components/settings/Settings', () => ({ Settings: () => null }));
vi.mock('~/components/chat/NoClick', () => ({ NoClick: () => null }));
vi.mock('~/components/command/CommandPalette', () => ({ CommandPalette: () => null }));
vi.mock('~/components/shared/popups/CreateCredentialDialog', () => ({ GlobalCreateCredentialDialog: () => null, openCreateCredential: () => {} }));
vi.mock('~/components/workflow/setup/SetupHandoffCover', () => ({ SetupHandoffCover: () => null }));
vi.mock('~/components/BalanceDisplay', () => ({ BalanceDisplay: () => null }));
vi.mock('~/components/debug/MimicBanner', () => ({ MimicBanner: () => null }));
vi.mock('~/cloud/components/shell/BillingMenuItems', () => ({ BillingMenuItems: () => null }));
vi.mock('~/cloud/components/referrals/InviteFriends', () => ({ InviteFriendsSidebarRow: () => null }));

afterEach(() => {
    cleanup();
    sessionStorage.clear();
});

describe('a first sign-in', () => {
    it('lands on the chat, never on onboarding questions', async () => {
        const Stub = createRoutesStub([{ path: '/dashboard', Component: DashboardRoute, HydrateFallback: () => null, loader }]);
        render(<Stub initialEntries={['/dashboard']} />);

        expect(await screen.findByText('NoClick chat')).toBeTruthy();
        expect(screen.queryByText('What are you here to build?')).toBeNull();
        expect(screen.queryByText('Automations')).toBeNull();
    });
});
