// @vitest-environment jsdom
// Resources with a platform registered (a fake one, as the hosted service
// registers the real one): every kind gets its tile and none is marked as
// sample data; the platform's items list beside the app's own; what they cost
// reads from their prices; a kind that couldn't be read says why; and a
// platform item's page carries its facts, a way to manage it and the body the
// platform draws. An automation's published interface is one of its apps and
// its tables are a database, each saying where it came from: there are no
// Interfaces or Tables kinds. Right after a domain is bought, one of the
// websites can go on it in the same flow, or not yet. A kind's trash lists
// under it, each item restorable or purged after a confirm. A bucket names the
// apps and agents that use it, an app opening its own page.
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import type { ReactNode } from 'react';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

const OVERVIEW = {
    generatedAt: '2026-10-09T12:00:00Z',
    credentials: [],
    workspaces: [],
    files: [
        {
            id: 'src_1',
            kind: 'resources',
            label: 'Leads',
            sublabel: 'R2',
            workflow: { id: 'wf_1', name: 'Lead intake', marks: [] },
            files: [
                // Kept where this instance keeps tables: a database of the automation's own on this page.
                { path: 'leads.csv', size: 0, mtime: '2026-10-08T00:00:00Z', kind: 'data', resourceId: 'res_1', resourceType: 'dataset', rows: 42 },
                { path: 'brief.pdf', size: 2048, mtime: '2026-10-07T00:00:00Z', kind: 'doc', resourceId: 'res_2', resourceType: 'file', mime: 'application/pdf' },
            ],
        },
        {
            id: 'src_2',
            kind: 'resources',
            label: 'Booking',
            sublabel: 'R2',
            workflow: { id: 'wf_2', name: 'Booking', marks: [] },
            // Kept in the platform database listed for the automation.
            files: [{ path: 'bookings', size: 0, mtime: '2026-10-09T00:00:00Z', kind: 'data', resourceId: 'res_3', resourceType: 'dataset', rows: 7, databaseId: 'db_1', table: 'bookings_1a2b3c4d' }],
        },
    ],
};

vi.mock('~/hooks/useDashboardOverview', () => ({ useDashboardOverview: () => ({ overview: OVERVIEW, loading: false }), fetchDashboardOverview: vi.fn() }));
vi.mock('~/hooks/useInstanceCapabilities', () => ({ useInstanceCapabilities: () => ({ publishing: true, billing: true }) }));
vi.mock('~/hooks/useOrgContext', () => ({ useOrgContext: () => [{ id: null }] }));
vi.mock('~/lib/socketCall', () => ({
    socketCall: vi.fn(async (event: string) => (event === 'usage:logs' ? { logs: [] } : { success: true })),
}));

import { socketCall } from '~/lib/socketCall';
import { ResourcesPage } from '~/components/shell/ResourcesPage';
import type { ResourceItem } from '~/components/shell/resources/model';
import { PlatformResourcesContext, registerPlatformResources, type PlatformResources, type Removal } from '~/components/shell/resources/platform';
import type { DomainRegistrar } from '~/hooks/useDomainPurchase';

const DOMAIN: ResourceItem = {
    id: 'dom_1',
    kind: 'domains',
    title: 'acmebooking.com',
    subtitle: 'Active · Serves booking',
    updatedAt: '2026-09-01T00:00:00Z',
    usedBy: [],
    price: { usd: 18, per: 'year' },
    platform: { facts: [['Status', 'Active']], url: 'https://acmebooking.com' },
};
const APP: ResourceItem = {
    id: 'prj_1',
    kind: 'apps',
    title: 'booking',
    subtitle: 'booking.noclick.site · Live',
    usedBy: [],
    price: { usd: 3.42, per: 'so-far' },
    platform: { facts: [['Address', 'booking.noclick.site']], url: 'https://booking.noclick.site' },
};

const BOOKING = { id: 'wf_2', name: 'Booking', marks: [] };
const PUBLISHED: ResourceItem = {
    id: 'prj_2',
    kind: 'apps',
    title: 'booking-form',
    subtitle: 'booking-form.noclick.site · Live',
    usedBy: [],
    origin: BOOKING,
    platform: {
        facts: [['Address', 'booking-form.noclick.site']],
        url: 'https://booking-form.noclick.site',
        unpublish: true,
    },
};
const BOOKING_TABLES: ResourceItem = {
    id: 'db_1',
    kind: 'databases',
    title: 'Booking',
    subtitle: 'SQLite · 1 table',
    usedBy: [],
    origin: BOOKING,
    tables: [],
    platform: { facts: [['Engine', 'SQLite']] },
};

function Body({ item }: { item: ResourceItem }) {
    return <p>The {item.title} body</p>;
}

const UPLOADS: ResourceItem = {
    id: 'bkt_1',
    kind: 'storage',
    title: 'uploads',
    subtitle: 'Private · 3 files · 2.0 KB',
    usedBy: [],
    users: [
        { kind: 'app', id: 'prj_1', name: 'booking', binding: 'FILES' },
        { kind: 'agent', id: 'agt_1', name: 'concierge', binding: null },
    ],
    platform: { facts: [['Access', 'Private']] },
};

const HELLO: ResourceItem = {
    id: 'inb_1',
    kind: 'email',
    title: 'hello@acmebooking.com',
    subtitle: 'Mail sent to it arrives here',
    usedBy: [],
    platform: { facts: [['Answered by', 'You']] },
};

const registrar: DomainRegistrar = { endings: ['com'], search: vi.fn(), checkout: vi.fn(), buy: vi.fn() };
// What the platform says removing each would do; the domain disconnects and leaves its page, the address is refused.
const DISCONNECT = {
    deletes: 'Disconnects acmebooking.com from NoClick. Its DNS stays as it is where it’s hosted, and it can be connected again.',
    depends_on_it: [],
    data_lost: [],
    stops_billing: [],
    reversible: true,
};
const disconnect = vi.fn(async () => ({ done: 'Disconnected acmebooking.com', gone: true }));
const refused = vi.fn(async (): Promise<{ done: string; gone: boolean }> => {
    throw new Error('An agent reads its mail: take it off the agent first.');
});
const removal = (item: ResourceItem): Removal | null =>
    item.id === DOMAIN.id
        ? { label: 'Remove', confirm: 'Disconnect acmebooking.com', preview: async () => DISCONNECT, run: disconnect }
        : item.id === HELLO.id
          ? { label: 'Delete', confirm: 'Delete hello@acmebooking.com', preview: async () => ({ ...DISCONNECT, deletes: 'Deletes the address.', data_lost: ['Its mail.'], reversible: false }), run: refused }
          : null;
const OLD_DB = { id: 'tr_1', name: 'orders-2025', trashedAt: '2026-10-07T12:00:00Z', purgeAfter: '2026-11-06T12:00:00Z' };
const TAKEN = { id: 'tr_2', name: 'leads', trashedAt: '2026-10-08T12:00:00Z', purgeAfter: '2026-11-07T12:00:00Z' };
const restore = vi.fn(async (entry: { id: string }) => {
    if (entry.id === TAKEN.id) throw new Error('A database named leads exists again, so this one can’t take its name back.');
});
const purge = vi.fn(async () => undefined);
const platform: PlatformResources = {
    items: { domains: [DOMAIN], email: [HELLO], apps: [APP, PUBLISHED], databases: [BOOKING_TABLES], storage: [UPLOADS], repos: [] },
    loading: false,
    errors: { repos: "Repos aren't enabled on this deployment yet." },
    spentThisMonth: { databases: 2.5, storage: 0.41 },
    refresh: vi.fn(),
    registrar,
    serveApp: vi.fn(async () => undefined),
    mailDomains: ['acmebooking.com'],
    createAddress: vi.fn(async () => 'inb_1'),
    Body,
    removal,
    trash: { databases: [OLD_DB, TAKEN] },
    restore,
    purge,
};

function FakePlatform({ children }: { children: ReactNode }) {
    return <PlatformResourcesContext.Provider value={platform}>{children}</PlatformResourcesContext.Provider>;
}

beforeAll(() => registerPlatformResources(FakePlatform));
// Radix's radio and checkbox measure themselves; jsdom has no ResizeObserver.
beforeEach(() => vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} }));
afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
});

function renderAt(search: string) {
    render(
        <MemoryRouter initialEntries={[`/dashboard?tab=resources${search}`]}>
            <ResourcesPage />
        </MemoryRouter>
    );
}

describe('Resources with a platform', () => {
    it('gives every kind a tile, with no sample data marked anywhere, and what each costs', async () => {
        renderAt('');
        const tiles = await screen.findByTestId('resources-overview');
        const tile = (kind: string) => within(tiles).getByTestId(`kind-tile-${kind}`);
        for (const kind of ['numbers', 'domains', 'email', 'apps', 'databases', 'storage', 'repos', 'files']) expect(tile(kind)).toBeTruthy();
        expect(tile('storage').textContent).toContain('1 bucket');
        expect(tile('storage').textContent).toContain('$0.41this month');
        expect(tile('email').textContent).toContain('1 address');
        for (const kind of ['interfaces', 'tables']) expect(within(tiles).queryByTestId(`kind-tile-${kind}`)).toBeNull();
        expect(screen.queryByText('Preview')).toBeNull();
        expect(tile('domains').textContent).toContain('$1.50a month');
        expect(tile('apps').textContent).toContain('2 websites');
        expect(tile('apps').textContent).toContain('$3.42this month');
        // The platform's database of Booking's tables, and Lead intake's tables kept here.
        expect(tile('databases').textContent).toContain('2 databases · 2 tables');
        expect(tile('databases').textContent).toContain('$2.50this month');
        expect(tile('files').textContent).toContain('1 file');
        // A month of the set prices (a domain's year over twelve); use-billed spend shows on its own tiles.
        expect(screen.getByText(/what it costs: \$1\.50 a month\./)).toBeTruthy();
    });

    it("lists a platform kind's items with their prices, and says why a kind couldn't be read", async () => {
        renderAt('&kind=domains');
        expect(await screen.findByText('acmebooking.com')).toBeTruthy();
        expect(screen.getByText('$1.50/mo')).toBeTruthy();
        expect(screen.getByRole('button', { name: /Buy a domain/ })).toBeTruthy();
        cleanup();
        renderAt('&kind=repos');
        expect((await screen.findByRole('alert')).textContent).toContain("Repos aren't enabled on this deployment yet.");
        cleanup();
        renderAt('&kind=databases');
        expect(await screen.findByText(/Billed by what they use: \$2\.50 so far this month\./)).toBeTruthy();
        cleanup();
        // A platform kind with nothing in it says what it is, and sends no one to the developer console.
        const errors = platform.errors;
        platform.errors = {};
        try {
            renderAt('&kind=repos');
            expect(await screen.findByText('No code yet')).toBeTruthy();
            expect(screen.queryByRole('link', { name: /Developer console/ })).toBeNull();
        } finally {
            platform.errors = errors;
        }
    });

    it("opens a platform item onto its facts, cost, its address and the platform's body, with no way into the developer console", async () => {
        renderAt('&kind=apps&resource=prj_1');
        const page = await screen.findByTestId('resource-detail');
        expect(within(page).getByRole('heading', { name: 'booking' })).toBeTruthy();
        expect(within(page).getByText('booking.noclick.site', { selector: 'dd' })).toBeTruthy();
        expect(within(page).getByText('$3.42 so far this month')).toBeTruthy();
        expect(within(page).queryByRole('link', { name: /Manage/ })).toBeNull();
        expect(within(page).queryAllByRole('link').filter((a) => a.getAttribute('href')?.startsWith('/dashboard/developers'))).toEqual([]);
        expect(within(page).getByRole('link', { name: /Open/ }).getAttribute('href')).toBe('https://booking.noclick.site');
        expect(within(page).getByText('The booking body')).toBeTruthy();
    });

    it('lists a bucket with what uses it and what storage cost this month, and its page names its apps and agents, an app opening its own page', async () => {
        renderAt('&kind=storage');
        const row = (await screen.findByText('uploads')).closest('button')!;
        expect(row.textContent).toContain('Private · 3 files · 2.0 KB');
        expect(row.textContent).toContain('booking+1');
        expect(screen.getByText(/Billed by what they use: \$0\.41 so far this month\./)).toBeTruthy();
        cleanup();
        renderAt('&kind=storage&resource=bkt_1');
        const page = await screen.findByTestId('resource-detail');
        const usedBy = within(page).getByRole('heading', { name: /Used by/ }).closest('section')!;
        expect(within(usedBy).getByRole('link', { name: /booking as FILES/ }).getAttribute('href')).toContain('kind=apps&resource=prj_1');
        expect(within(usedBy).getByText('concierge').closest('a')).toBeNull();
        expect(within(page).getByText('Billed by use')).toBeTruthy();
        expect(within(page).getByText('The uploads body')).toBeTruthy();
    });

    it('lists a published interface as an app, saying which automation it was built in, and unpublishes it from its page', async () => {
        renderAt('&kind=apps');
        expect(await screen.findByText('booking-form')).toBeTruthy();
        expect(screen.getByText('Built in Booking')).toBeTruthy();
        cleanup();
        renderAt('&kind=apps&resource=prj_2');
        const page = await screen.findByTestId('resource-detail');
        expect(within(page).getByText(/Built in the/).textContent).toBe('Built in the Booking automation');
        fireEvent.click(within(page).getByRole('button', { name: /Unpublish/ }));
        fireEvent.click(within(page).getByRole('button', { name: 'Take it down' }));
        await vi.waitFor(() => expect(socketCall).toHaveBeenCalledWith('publish:unpublish', { project_id: 'prj_2' }));
    });

    it('removes a domain from its page: what the platform says it does first, then the confirm, then back to its list', async () => {
        renderAt('&kind=domains&resource=dom_1');
        const page = await screen.findByTestId('resource-detail');
        fireEvent.click(within(page).getByRole('button', { name: 'Remove' }));
        const panel = await within(page).findByTestId('removal-panel');
        expect(await within(panel).findByText(DISCONNECT.deletes)).toBeTruthy();
        expect(within(panel).getByText('It can be undone.')).toBeTruthy();
        fireEvent.click(within(panel).getByRole('button', { name: 'Cancel' }));
        expect(within(page).queryByTestId('removal-panel')).toBeNull();

        fireEvent.click(within(page).getByRole('button', { name: 'Remove' }));
        fireEvent.click(await within(page).findByRole('button', { name: 'Disconnect acmebooking.com' }));
        await waitFor(() => expect(disconnect).toHaveBeenCalledTimes(1));
        // Gone: the page leaves for the domains list.
        await waitFor(() => expect(screen.queryByTestId('resource-detail')).toBeNull());
    });

    it('says why a removal was refused and stays, and offers none where the platform has none', async () => {
        renderAt('&kind=email&resource=inb_1');
        const page = await screen.findByTestId('resource-detail');
        fireEvent.click(within(page).getByRole('button', { name: 'Delete' }));
        const panel = await within(page).findByTestId('removal-panel');
        expect(await within(panel).findByText('Data lost:', { exact: false })).toBeTruthy();
        expect(within(panel).getByText('It can’t be undone.')).toBeTruthy();
        fireEvent.click(within(panel).getByRole('button', { name: 'Delete hello@acmebooking.com' }));
        expect((await within(panel).findByRole('alert')).textContent).toBe('An agent reads its mail: take it off the agent first.');
        expect(screen.getByTestId('resource-detail')).toBeTruthy();
        cleanup();

        renderAt('&kind=apps&resource=prj_1');
        const app = await screen.findByTestId('resource-detail');
        expect(within(app).queryByRole('button', { name: /^(Remove|Delete)$/ })).toBeNull();
    });

    it("lists a kind's trash under it: restores one, says why another can't come back, purges after a confirm", async () => {
        renderAt('&kind=databases');
        const trash = await screen.findByTestId('resources-trash');
        const row = within(trash).getByTestId('trash-row-tr_1');
        expect(row.textContent).toContain('orders-2025');
        fireEvent.click(within(row).getByRole('button', { name: 'Restore' }));
        await waitFor(() => expect(restore).toHaveBeenCalledWith(OLD_DB));

        const taken = within(trash).getByTestId('trash-row-tr_2');
        fireEvent.click(within(taken).getByRole('button', { name: 'Restore' }));
        expect((await within(taken).findByRole('alert')).textContent).toContain('exists again');

        fireEvent.click(within(row).getByRole('button', { name: 'Purge now' }));
        expect(purge).not.toHaveBeenCalled();
        fireEvent.click(within(row).getByRole('button', { name: 'Delete for good' }));
        await waitFor(() => expect(purge).toHaveBeenCalledWith(OLD_DB));
        cleanup();

        // A kind with nothing in the trash shows none.
        renderAt('&kind=domains');
        await screen.findByText('acmebooking.com');
        expect(screen.queryByTestId('resources-trash')).toBeNull();
    });

    it('lists an automation’s tables as a database: the platform’s where it keeps them, else one named for the automation', async () => {
        renderAt('&kind=databases');
        expect(await screen.findByText('Booking')).toBeTruthy();
        expect(screen.getByText('Lead intake')).toBeTruthy();
        expect(screen.getByText('1 table · 42 rows')).toBeTruthy();
        cleanup();
        renderAt('&kind=databases&resource=db_1');
        let page = await screen.findByTestId('resource-detail');
        expect(within(page).getByRole('heading', { name: /^Tables/ })).toBeTruthy();
        expect(within(page).getByText('bookings')).toBeTruthy();
        expect(within(page).getByText('7 rows')).toBeTruthy();
        // Its tables, not the platform's schema view.
        expect(within(page).queryByText('The Booking body')).toBeNull();
        cleanup();
        renderAt('&kind=databases&resource=tables:wf_1');
        page = await screen.findByTestId('resource-detail');
        expect(within(page).getByRole('heading', { name: 'Lead intake' })).toBeTruthy();
        expect(within(page).getByText('leads.csv')).toBeTruthy();
        expect(within(page).getByText(/Built in the/).textContent).toBe('Built in the Lead intake automation');
    });

    it('lists files without the tables', async () => {
        renderAt('&kind=files');
        expect(await screen.findByText('brief.pdf')).toBeTruthy();
        expect(screen.queryByText('leads.csv')).toBeNull();
    });

    it('opens the buy-a-domain page on the platform’s registrar', async () => {
        renderAt('&kind=domains');
        fireEvent.click(await screen.findByRole('button', { name: /Buy a domain/ }));
        expect(await screen.findByRole('heading', { name: 'Buy a domain' })).toBeTruthy();
        expect(registrar.search).toHaveBeenCalledWith({ name: 'acmebooking', ending: null });
    });

    it('offers to put a website on a domain right after buying it, and goes on without one when asked', async () => {
        vi.mocked(registrar.search).mockResolvedValue({ asked: { domain: 'acme.io', status: 'available' }, offers: [{ domain: 'acme.io', ending: 'io', priceUsd: 45, years: 1, renewalUsd: 45 }] });
        vi.mocked(registrar.checkout).mockResolvedValue({ agreementUrl: 'https://noclick.com/legal/domain-registration', onFile: { name: 'Dana Reyes', email: 'dana@example.com' } });
        vi.mocked(registrar.buy).mockResolvedValue(undefined);
        const buy = async () => {
            renderAt('&kind=domains&new=1&name=acme.io');
            fireEvent.click(await screen.findByRole('button', { name: 'Buy' }));
            const confirm = await screen.findByRole('button', { name: 'Buy for $45.00' });
            await waitFor(() => expect((confirm as HTMLButtonElement).disabled).toBe(false));
            fireEvent.click(confirm);
            await screen.findByRole('heading', { name: 'Use acme.io for a website?' });
        };

        await buy();
        expect(screen.getAllByRole('radio').map((r) => r.closest('label')!.textContent)).toEqual(['bookingbooking.noclick.site · Live', 'booking-formbooking-form.noclick.site · Live']);
        expect((screen.getByRole('button', { name: 'Use acme.io' }) as HTMLButtonElement).disabled).toBe(true);
        fireEvent.click(screen.getByRole('radio', { name: /^booking-form/ }));
        fireEvent.click(screen.getByRole('button', { name: 'Use acme.io' }));
        expect(await screen.findByRole('heading', { name: 'Domains' })).toBeTruthy();
        expect(platform.serveApp).toHaveBeenCalledWith('prj_2', 'acme.io');

        cleanup();
        vi.mocked(platform.serveApp).mockClear();
        await buy();
        fireEvent.click(screen.getByRole('button', { name: 'Not now' }));
        expect(await screen.findByRole('heading', { name: 'Domains' })).toBeTruthy();
        expect(platform.serveApp).not.toHaveBeenCalled();
        expect(registrar.buy).toHaveBeenCalledTimes(2);
    });

    it('says why a website could not go on the domain, and stays on the step', async () => {
        vi.mocked(platform.serveApp).mockRejectedValueOnce(new Error('acme.io takes an inbox’s mail, so it can’t serve a web page too.'));
        renderAt('&kind=domains&new=1&name=acme.io');
        fireEvent.click(await screen.findByRole('button', { name: 'Buy' }));
        const confirm = await screen.findByRole('button', { name: 'Buy for $45.00' });
        await waitFor(() => expect((confirm as HTMLButtonElement).disabled).toBe(false));
        fireEvent.click(confirm);
        fireEvent.click(await screen.findByRole('radio', { name: /^booking-form/ }));
        fireEvent.click(screen.getByRole('button', { name: 'Use acme.io' }));
        expect((await screen.findByRole('alert')).textContent).toBe('acme.io takes an inbox’s mail, so it can’t serve a web page too.');
        expect(screen.getByRole('heading', { name: 'Use acme.io for a website?' })).toBeTruthy();
    });

    it('makes an email address on one of your domains and opens it', async () => {
        vi.mocked(platform.createAddress).mockClear();
        renderAt('&kind=email');
        expect(await screen.findByText('hello@acmebooking.com')).toBeTruthy();
        expect(screen.getByText(/Billed by what they use\./)).toBeTruthy();
        fireEvent.click(screen.getByRole('button', { name: /New address/ }));
        expect(await screen.findByRole('heading', { name: 'New email address' })).toBeTruthy();
        const domain = screen.getByRole('combobox', { name: 'Domain' }) as HTMLSelectElement;
        expect([...domain.options].map((o) => o.textContent)).toEqual(['acmebooking.com', 'NoClick’s mail domain']);
        expect(domain.value).toBe('acmebooking.com');
        const create = screen.getByRole('button', { name: 'Create address' }) as HTMLButtonElement;
        expect(create.disabled).toBe(true);
        fireEvent.change(screen.getByLabelText('Address'), { target: { value: ' Sales ' } });
        fireEvent.click(create);
        await waitFor(() => expect(platform.createAddress).toHaveBeenCalledWith('sales', 'acmebooking.com'));
        // The new address opens on its page.
        const page = await screen.findByTestId('resource-detail');
        expect(within(page).getByRole('heading', { name: 'hello@acmebooking.com' })).toBeTruthy();
    });

    it("makes one on NoClick's mail domain, and says why an address couldn't be made", async () => {
        vi.mocked(platform.createAddress).mockClear();
        vi.mocked(platform.createAddress).mockRejectedValueOnce(new Error('sales@acmebooking.com is taken.'));
        renderAt('&kind=email&new=1');
        fireEvent.change(await screen.findByLabelText('Address'), { target: { value: 'sales' } });
        fireEvent.click(screen.getByRole('button', { name: 'Create address' }));
        expect((await screen.findByRole('alert')).textContent).toBe('sales@acmebooking.com is taken.');
        expect(screen.getByRole('heading', { name: 'New email address' })).toBeTruthy();
        fireEvent.change(screen.getByRole('combobox', { name: 'Domain' }), { target: { value: '' } });
        fireEvent.click(screen.getByRole('button', { name: 'Create address' }));
        await waitFor(() => expect(platform.createAddress).toHaveBeenLastCalledWith('sales', null));
    });

    it('opens an address onto its page, with the platform drawing its mail', async () => {
        renderAt('&kind=email&resource=inb_1');
        const page = await screen.findByTestId('resource-detail');
        expect(within(page).getByRole('heading', { name: 'hello@acmebooking.com' })).toBeTruthy();
        expect(within(page).getByText('The hello@acmebooking.com body')).toBeTruthy();
    });
});
