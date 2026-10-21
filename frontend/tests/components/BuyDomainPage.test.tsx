// @vitest-environment jsdom
// Resources › Domains › Buy a domain over a fake registrar: the page opens on
// the name your domains have and names the one you own instead of offering
// it; Buy opens a checkout with the price and term; a purchase waits on the
// registrant (on file, or details entered with the agreement accepted) and on
// a trademark notice when the name has one; and confirming buys exactly that
// offer, once.
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('sonner', () => ({ toast: { success: vi.fn() } }));
import { BuyDomainPage } from '~/components/shell/resources/BuyDomainPage';
import { DomainRegistrarError, type DomainCheckout, type DomainOffer, type DomainPurchaseDetails, type DomainQuery, type DomainRegistrar } from '~/hooks/useDomainPurchase';

// Radix's checkbox measures itself; jsdom has no ResizeObserver.
beforeEach(() => vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} }));
afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
});

const AI: DomainOffer = { domain: 'acme.ai', ending: 'ai', priceUsd: 160, years: 2, renewalUsd: 150 };
const IO: DomainOffer = { domain: 'acme.io', ending: 'io', priceUsd: 45, years: 1, renewalUsd: 45, claimsNotice: 'ACME is a registered trademark.' };
const CLOSE: DomainOffer = { domain: 'getacme.com', ending: 'com', priceUsd: 12.99, years: 1, renewalUsd: 12.99, close: true };

function fakeRegistrar(checkout: DomainCheckout, overrides: Partial<DomainRegistrar> = {}) {
    const searches: DomainQuery[] = [];
    const purchases: { offer: DomainOffer; details: DomainPurchaseDetails }[] = [];
    const registrar: DomainRegistrar = {
        endings: ['com', 'ai', 'io'],
        async search(query) {
            searches.push(query);
            return { asked: { domain: `${query.name}.${query.ending ?? 'com'}`, status: 'taken' }, offers: [{ ...AI, domain: `${query.name}.com`, ending: 'com', priceUsd: 12.99, years: 1 }, AI, IO, CLOSE] };
        },
        checkout: async () => checkout,
        async buy(offer, details) {
            purchases.push({ offer, details });
        },
        ...overrides,
    };
    return { registrar, searches, purchases };
}

function renderPage(registrar: DomainRegistrar, log: string[] = []) {
    render(
        <MemoryRouter>
            <BuyDomainPage registrar={registrar} seed="acme" owned={['acme.com']} onBack={() => log.push('back')} onBought={(d) => log.push(`bought ${d}`)} onOpen={(d) => log.push(`open ${d}`)} />
        </MemoryRouter>
    );
    return log;
}

const rows = () => screen.getAllByTestId('available-domain');
const ON_FILE: DomainCheckout = { agreementUrl: 'https://noclick.test/legal/domains', onFile: { name: 'Ana Silva', email: 'ana@example.com' } };

describe('the buy-a-domain page', () => {
    it('opens on your name, names the one you own instead of offering it, and prices each offer for its term', async () => {
        const { registrar, searches } = fakeRegistrar(ON_FILE);
        const log = renderPage(registrar);
        await waitFor(() => expect(rows()).toHaveLength(3));
        expect(searches[0]).toEqual({ name: 'acme', ending: null });
        expect(rows().map((r) => r.textContent)).toEqual([
            expect.stringContaining('acme.ai$160.00 for 2 years'),
            expect.stringContaining('acme.io$45.00 a year · Trademark notice'),
            expect.stringContaining('getacme.com$12.99 a year · A close name'),
        ]);
        const asked = screen.getByTestId('asked-domain');
        expect(asked.textContent).toContain('acme.com is already yours.');
        fireEvent.click(within(asked).getByRole('button', { name: 'Open it' }));
        expect(log).toEqual(['open acme.com']);
    });

    it('searches the name on an ending from its chip', async () => {
        const { registrar, searches } = fakeRegistrar(ON_FILE);
        renderPage(registrar);
        await waitFor(() => expect(rows()).toHaveLength(3));
        fireEvent.click(screen.getByRole('button', { name: '.io' }));
        await waitFor(() => expect(searches).toHaveLength(2));
        expect(searches[1]).toEqual({ name: 'acme', ending: 'io' });
        expect((screen.getByLabelText('The domain or name to search for') as HTMLInputElement).value).toBe('acme.io');
    });

    it("buys with the account's registrant on file, at the offer's price, once", async () => {
        const { registrar, purchases } = fakeRegistrar(ON_FILE);
        const log = renderPage(registrar);
        await waitFor(() => expect(rows()).toHaveLength(3));
        fireEvent.click(within(rows()[0]).getByRole('button', { name: 'Buy' }));
        expect(purchases).toHaveLength(0);
        const form = await screen.findByRole('form', { name: 'Buy acme.ai' });
        expect(form.textContent).toContain('$160.00');
        expect(form.textContent).toContain('For 2 years');
        expect(form.textContent).toContain('It renews at $150.00 every 2 years');
        expect((await screen.findByTestId('registrant-on-file')).textContent).toContain('Ana Silva (ana@example.com)');
        const buy = screen.getByRole('button', { name: 'Buy for $160.00' });
        await waitFor(() => expect((buy as HTMLButtonElement).disabled).toBe(false));
        fireEvent.click(buy);
        fireEvent.click(buy);
        await waitFor(() => expect(log).toEqual(['bought acme.ai']));
        expect(purchases).toEqual([{ offer: AI, details: { registrant: undefined, acceptClaims: false } }]);
    });

    it('takes details when nobody is on file, and buys only once they and the agreement are in', async () => {
        const { registrar, purchases } = fakeRegistrar({ agreementUrl: 'https://noclick.test/legal/domains', onFile: null });
        renderPage(registrar);
        await waitFor(() => expect(rows()).toHaveLength(3));
        fireEvent.click(within(rows()[0]).getByRole('button', { name: 'Buy' }));
        const buy = await screen.findByRole('button', { name: 'Buy for $160.00' });
        expect(screen.getByRole('link', { name: /domain registration agreement/ }).getAttribute('href')).toBe('https://noclick.test/legal/domains');
        const fill = (label: string, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } });
        fill('Full name', 'Ana Silva');
        fill('Email', 'ana@example.com');
        fill('Phone', '+14155550123');
        fill('Street address', '500 Market St');
        fill('City', 'San Francisco');
        fill('State or region', 'CA');
        fill('Postal code', '94105');
        fill('Country (two letters)', 'us');
        expect((buy as HTMLButtonElement).disabled).toBe(true);
        fireEvent.click(screen.getByRole('checkbox', { name: /I accept the/ }));
        await waitFor(() => expect((buy as HTMLButtonElement).disabled).toBe(false));
        fireEvent.click(buy);
        await waitFor(() => expect(purchases).toHaveLength(1));
        const { registrant, acceptClaims } = purchases[0].details;
        expect(acceptClaims).toBe(false);
        expect(registrant).toMatchObject({ name: 'Ana Silva', email: 'ana@example.com', country: 'US', postalCode: '94105', region: 'CA' });
        expect(registrant?.organization).toBeUndefined();
        expect(registrant?.agreementAcceptedAt).toBeInstanceOf(Date);
    });

    it('starts the details from what NoClick knows of the owner, so they type only their address', async () => {
        const known = { name: 'Ana Silva', email: 'ana@example.com', phone: '+14155550123' };
        const { registrar, purchases } = fakeRegistrar({ agreementUrl: 'https://noclick.test/legal/domains', onFile: null, known });
        renderPage(registrar);
        await waitFor(() => expect(rows()).toHaveLength(3));
        fireEvent.click(within(rows()[0]).getByRole('button', { name: 'Buy' }));
        const buy = await screen.findByRole('button', { name: 'Buy for $160.00' });
        const value = (label: string) => (screen.getByLabelText(label) as HTMLInputElement).value;
        await waitFor(() => expect([value('Full name'), value('Email'), value('Phone')]).toEqual([known.name, known.email, known.phone]));
        expect(value('Street address')).toBe('');
        const fill = (label: string, text: string) => fireEvent.change(screen.getByLabelText(label), { target: { value: text } });
        // What they know better wins: a name typed over the one NoClick had stays.
        fill('Full name', 'Ana M. Silva');
        fill('Street address', '500 Market St');
        fill('City', 'San Francisco');
        fill('State or region', 'CA');
        fill('Postal code', '94105');
        fill('Country (two letters)', 'US');
        fireEvent.click(screen.getByRole('checkbox', { name: /I accept the/ }));
        await waitFor(() => expect((buy as HTMLButtonElement).disabled).toBe(false));
        fireEvent.click(buy);
        await waitFor(() => expect(purchases).toHaveLength(1));
        expect(purchases[0].details.registrant).toMatchObject({ ...known, name: 'Ana M. Silva', address: '500 Market St', country: 'US' });
    });

    it('holds a name with a trademark notice until the notice is accepted', async () => {
        const { registrar, purchases } = fakeRegistrar(ON_FILE);
        renderPage(registrar);
        await waitFor(() => expect(rows()).toHaveLength(3));
        fireEvent.click(within(rows()[1]).getByRole('button', { name: 'Buy' }));
        expect(await screen.findByText('ACME is a registered trademark.')).toBeTruthy();
        const buy = screen.getByRole('button', { name: 'Buy for $45.00' });
        await screen.findByTestId('registrant-on-file');
        expect((buy as HTMLButtonElement).disabled).toBe(true);
        fireEvent.click(screen.getByRole('checkbox', { name: /still want acme.io/ }));
        await waitFor(() => expect((buy as HTMLButtonElement).disabled).toBe(false));
        fireEvent.click(buy);
        await waitFor(() => expect(purchases).toHaveLength(1));
        expect(purchases[0]).toEqual({ offer: IO, details: { registrant: undefined, acceptClaims: true } });
    });

    it('Back leaves the checkout for the results without buying', async () => {
        const { registrar, purchases } = fakeRegistrar(ON_FILE);
        renderPage(registrar);
        await waitFor(() => expect(rows()).toHaveLength(3));
        fireEvent.click(within(rows()[2]).getByRole('button', { name: 'Buy' }));
        fireEvent.click(await screen.findByRole('button', { name: 'Back' }));
        await waitFor(() => expect(rows()).toHaveLength(3));
        expect(purchases).toHaveLength(0);
    });

    it('says when this instance sells no domains, and offers funds, never a plan, when the balance is short of a purchase', async () => {
        const off = fakeRegistrar(ON_FILE, {
            search: async () => {
                throw new DomainRegistrarError("Domains aren't enabled on this deployment yet.", 'unavailable');
            },
        });
        renderPage(off.registrar);
        expect((await screen.findByTestId('domains-unavailable')).textContent).toContain("Domains aren't enabled on this deployment yet.");
        cleanup();
        const short = fakeRegistrar(ON_FILE, {
            buy: async () => {
                throw new DomainRegistrarError('Your account needs at least $5.00 in its balance to buy this: $4.99 left.', 'credits');
            },
        });
        renderPage(short.registrar);
        await waitFor(() => expect(rows()).toHaveLength(3));
        fireEvent.click(within(rows()[2]).getByRole('button', { name: 'Buy' }));
        const buy = await screen.findByRole('button', { name: 'Buy for $12.99' });
        await waitFor(() => expect((buy as HTMLButtonElement).disabled).toBe(false));
        fireEvent.click(buy);
        const refused = await screen.findByRole('alert');
        expect(refused.textContent).toContain('needs at least $5.00 in its balance');
        expect(within(refused).getByRole('link', { name: 'Top up' }).getAttribute('href')).toBe('/dashboard?action=topup');
        expect(screen.queryByRole('dialog')).toBeNull();
    });
});
