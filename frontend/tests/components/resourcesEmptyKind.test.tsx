// @vitest-environment happy-dom
// An empty Resources kind page says what the kind is once, in the page's own line: the empty state under it names
// what's missing and the ways to get one, without repeating that line. Over every kind the open edition lists.
import { cleanup, render, screen } from '@testing-library/react';
import { createRoutesStub } from 'react-router';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

vi.mock('~/hooks/useDashboardOverview', () => ({
    useDashboardOverview: () => ({ overview: null, loading: false, error: null, dismissed: [], refresh: () => undefined }),
    fetchDashboardOverview: async () => undefined,
}));
vi.mock('~/lib/socketCall', () => ({ socketCall: () => new Promise(() => undefined) }));
vi.mock('~/components/shell/AppShell', () => ({ useInPhoneShell: () => false, PhoneBarBack: () => null }));
import { ResourcesView } from '~/components/shell/ResourcesPage';
import { KINDS } from '~/components/shell/resources/model';

beforeEach(() => vi.stubGlobal('fetch', async () => new Response(null, { status: 404 })));
afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
});

it.each(KINDS.filter((k) => !k.platform).map((k) => [k.label, k] as const))('%s, empty, says what it is once', async (_, kind) => {
    const Stub = createRoutesStub([{ path: '/dashboard', Component: ResourcesView }]);
    const view = render(<Stub initialEntries={[`/dashboard?tab=resources&kind=${kind.id}`]} />);
    await screen.findByText(`No ${kind.label.toLowerCase()} yet`);
    expect(view.container.textContent!.split(kind.empty)).toHaveLength(2);
    expect(screen.getByRole('heading', { name: kind.label }).nextElementSibling!.textContent).toContain(kind.empty);
});
