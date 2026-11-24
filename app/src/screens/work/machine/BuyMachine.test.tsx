// @vitest-environment happy-dom
// Buying a machine for an agent over the fake /v1, at the lab's prices and stock: sizes worth buying "from" their best
// price, a sold-out one greyed and one another beats left out; where it runs after the size, cheapest picked, a region
// where it's sold out saying so; a quote that names the host (the picker never does) with Buy held a moment; and a host
// running out between the pick and Buy re-quoting in place, the old price struck through, nothing charged at a price
// that wasn't shown.
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Machine } from 'noclick';
import { fakeWork } from '../agents/fixtures/workAgents';
import { WorkProviders } from '../agents/fixtures/providers';
import { createWorkLive } from '@/sdk/live';
import { holding } from '@/sdk/heldFixture';
import { workFixtureClient } from '../fixtures/client';
import { BuyMachine } from './BuyMachine';

afterEach(cleanup);

function open(hosts: 'two' | 'one' = 'two') {
    const fake = fakeWork({ machineHosts: hosts });
    const onBought = vi.fn<(machine: Machine) => void>();
    const live = createWorkLive();
    render(
        <WorkProviders client={fake.client} live={live}>
            <BuyMachine agent={{ name: 'Atlas', made: true }} onBought={onBought} onClose={() => undefined} />
        </WorkProviders>
    );
    return { fake, onBought, live };
}

const dialog = () => screen.getByTestId('buy-machine');
const rows = () => within(dialog()).getAllByRole('radio');
const row = (name: string) => within(dialog()).getByRole('radio', { name: new RegExp(`^${name}`) });
const buyButton = () => within(dialog()).getByRole('button', { name: /^Buy/ });
const noHost = () => expect(dialog().textContent).not.toMatch(/Hetzner|DigitalOcean/);
const purchases = (fake: ReturnType<typeof fakeWork>) => fake.requests.filter((r) => r.method === 'POST' && r.path === '/v1/machines').map((r) => r.body);

async function toConfirm(size: string, region?: string) {
    await waitFor(() => expect(rows().length).toBeGreaterThan(0));
    fireEvent.click(row(size));
    fireEvent.click(within(dialog()).getByRole('button', { name: 'Choose where' }));
    if (region) fireEvent.click(row(region));
    fireEvent.click(within(dialog()).getByRole('button', { name: /^Continue/ }));
}
const unheld = () => waitFor(() => expect(buyButton().hasAttribute('disabled')).toBe(false));

describe('the sizes', () => {
    it('lists what’s worth buying from its best price and greys a sold-out size, leaving out one another beats', async () => {
        open();
        await waitFor(() => expect(rows()).toHaveLength(3));
        expect(rows().map((r) => r.textContent)).toEqual([
            'Small2 vCPU · 4 GB · about 2 agents at onceFrom$8.39/mo',
            'Large8 vCPU · 16 GB · about 8 agents at onceFrom$22.79/mo',
            'XLarge16 vCPU · 32 GB · about 16 agents at onceNone anywhere right now.Sold out',
        ]);
        expect(screen.queryByText(/Medium/)).toBeNull();
        const xlarge = row('XLarge');
        expect(xlarge.getAttribute('aria-disabled')).toBe('true');
        fireEvent.click(xlarge);
        expect(xlarge.getAttribute('aria-checked')).toBe('false');
        expect(row('Small').getAttribute('aria-checked')).toBe('true');
        noHost();
    });

    it('with one host at one price everywhere, each size says its price with no “from”', async () => {
        open('one');
        await waitFor(() => expect(rows()).toHaveLength(3));
        expect(rows().map((r) => r.textContent)).toEqual([
            'Small2 vCPU · 4 GB · about 2 agents at once$31.20/mo',
            'Medium4 vCPU · 8 GB · about 4 agents at once$62.40/mo',
            'Large8 vCPU · 16 GB · about 8 agents at once$124.80/mo',
        ]);
        noHost();
    });
});

describe('where it runs', () => {
    it('comes after the size: its regions cheapest first, the cheapest picked, one where it’s sold out saying so', async () => {
        open();
        await waitFor(() => expect(rows()).toHaveLength(3));
        fireEvent.click(row('Large'));
        fireEvent.click(within(dialog()).getByRole('button', { name: 'Choose where' }));
        expect(screen.getByText('Where Large runs')).toBeTruthy();
        expect(rows().map((r) => r.textContent)).toEqual([
            'Europe160 GB disk · The European Economic Area$22.79/mo',
            'US West320 GB disk · The western United States$124.80/mo',
            'Asia Pacific320 GB disk · Asia and the Pacific$124.80/mo',
            'India320 GB disk · India$124.80/mo',
            'US EastThe eastern United StatesSold out here',
        ]);
        expect(row('Europe').getAttribute('aria-checked')).toBe('true');
        expect(row('US East').getAttribute('aria-disabled')).toBe('true');
        noHost();
        fireEvent.click(row('India'));
        expect(within(dialog()).getByRole('button', { name: /^Continue/ }).textContent).toBe('Continue · $124.80 a month');
        // Back to the sizes, and on again.
        fireEvent.click(within(dialog()).getByRole('button', { name: 'Sizes' }));
        expect(row('Large').getAttribute('aria-checked')).toBe('true');
    });
});

describe('the quote', () => {
    it('names the host and holds Buy a moment, then buys exactly what it quoted and follows it until it runs', async () => {
        const { fake, onBought, live } = open();
        await toConfirm('Large');
        expect(screen.getByText('Buy Large in Europe?')).toBeTruthy();
        expect(within(screen.getByTestId('step-what')).getByText('8 vCPU · 16 GB · 160 GB disk · on Hetzner')).toBeTruthy();
        expect(buyButton().textContent).toBe('Buy for $22.79 a month');
        expect(buyButton().hasAttribute('disabled')).toBe(true);
        fireEvent.click(buyButton());
        expect(purchases(fake)).toEqual([]);
        await unheld();
        await act(async () => fireEvent.click(buyButton()));
        await waitFor(() => expect(onBought).toHaveBeenCalled());
        expect(purchases(fake)).toEqual([{ name: 'atlas-box', size: 'large', region: 'eu', host: 'hetzner', max_monthly_usd: 22.79 }]);
        expect(onBought.mock.calls[0][0].name).toBe('atlas-box');
        expect(screen.getByText('Bought Large in Europe')).toBeTruthy();
        expect(within(screen.getByTestId('step-start')).getByText('Starting atlas-box')).toBeTruthy();
        expect(screen.getByTestId('step-start').getAttribute('data-status')).toBe('busy');
        // Its frame says it moved; read again, it's running.
        const bought = fake.machines.find((m) => m.name === 'atlas-box')!;
        bought.status = 'running';
        act(() => live.deliver('platform:resource', { kind: 'machine', id: String(bought.id), status: 'running', parent_id: null, version: null }));
        await waitFor(() => expect(screen.getByText('atlas-box is running', { selector: 'h2' })).toBeTruthy());
        expect(screen.getByTestId('step-start').getAttribute('data-status')).toBe('done');
        expect(within(dialog()).getByRole('button', { name: 'Done' })).toBeTruthy();
    });

    it('re-quotes in place when the host runs out as Buy is pressed: the new price over the old, why, and Buy held again', async () => {
        const { fake, onBought } = open();
        await toConfirm('Small');
        await unheld();
        fake.stock.out.add('hetzner:eu:small');
        await act(async () => fireEvent.click(buyButton()));
        await waitFor(() => expect(screen.getByText('What you can buy changed')).toBeTruthy());
        expect(screen.getByTestId('was-price').textContent).toBe('$8.39');
        expect(screen.getByTestId('new-price').textContent).toBe('$22.79');
        expect(screen.getByText(/^Hetzner’s Small sold out in Europe as you pressed Buy, so nothing was charged\. Large is now the cheapest machine with at least that much room\.$/)).toBeTruthy();
        expect(within(screen.getByTestId('step-what')).getByText('Large in Europe')).toBeTruthy();
        expect(buyButton().textContent).toBe('Buy for $22.79 a month');
        // A second press of the same click lands on a held Buy: nothing is agreed to at a price not yet read.
        expect(buyButton().hasAttribute('disabled')).toBe(true);
        fireEvent.click(buyButton());
        expect(fake.machines.filter((m) => m.kind === 'noclick').map((m) => m.name)).toEqual(['ops-box']);
        await unheld();
        await act(async () => fireEvent.click(buyButton()));
        await waitFor(() => expect(onBought).toHaveBeenCalled());
        expect(purchases(fake).map((b) => [(b as { size: string }).size, (b as { max_monthly_usd: number }).max_monthly_usd])).toEqual([
            ['small', 8.39],
            ['large', 22.79],
        ]);
    });

    it('says when it’s the same size there on another host, at its price', async () => {
        const { fake } = open();
        await toConfirm('Large');
        await unheld();
        fake.stock.out.add('hetzner:eu:large');
        await act(async () => fireEvent.click(buyButton()));
        await waitFor(() => expect(screen.getByText('The price changed')).toBeTruthy());
        expect(screen.getByText(/DigitalOcean has one there at this price, with a 320 GB disk\.$/)).toBeTruthy();
        expect(buyButton().textContent).toBe('Buy for $124.80 a month');
    });

    it('offers the cheapest with its room where it was picked, and picking it re-quotes and holds Buy again', async () => {
        const { fake } = open();
        await toConfirm('Small', 'US West');
        await unheld();
        fake.stock.out.add('digitalocean:us-west:small');
        await act(async () => fireEvent.click(buyButton()));
        await waitFor(() => expect(screen.getByText(/Europe has the next cheapest Small, at this price\.$/)).toBeTruthy());
        const other = within(dialog()).getByRole('button', { name: 'Or Large in US West for $124.80 a month' });
        await unheld();
        fireEvent.click(other);
        expect(screen.getByText(/^DigitalOcean’s Small sold out in US West as you pressed Buy, so nothing was charged\. You chose Large instead\.$/)).toBeTruthy();
        expect(screen.getByTestId('was-price').textContent).toBe('$8.39');
        expect(buyButton().textContent).toBe('Buy for $124.80 a month');
        expect(buyButton().hasAttribute('disabled')).toBe(true);
    });

    it('with nothing like it left, says so and charges nothing', async () => {
        const { fake } = open('one');
        await toConfirm('Small');
        await unheld();
        for (const r of ['us-east', 'us-west', 'eu', 'ap', 'in']) for (const s of ['small', 'medium', 'large']) fake.stock.out.add(`digitalocean:${r}:${s}`);
        await act(async () => fireEvent.click(buyButton()));
        await waitFor(() => expect(screen.getByText('Small sold out in US East')).toBeTruthy());
        expect(screen.getByText('DigitalOcean ran out as you pressed Buy. Nothing was charged.')).toBeTruthy();
        expect(screen.getByText('Nothing like it is in stock anywhere right now.')).toBeTruthy();
        expect(fake.machines.filter((m) => m.kind === 'noclick')).toHaveLength(1);
    });

    it('a refusal that isn’t about stock says so in its own words, and Buy can be pressed again', async () => {
        const { fake } = open();
        await toConfirm('Small');
        await unheld();
        fake.failNext('POST', '/v1/machines', 400, 'The account’s company isn’t vetted yet.');
        await act(async () => fireEvent.click(buyButton()));
        await waitFor(() => expect(screen.getByRole('alert').textContent).toBe('The account’s company isn’t vetted yet.'));
        expect(screen.getByText('Buy Small in Europe?')).toBeTruthy();
        expect(buyButton().hasAttribute('disabled')).toBe(false);
    });
});

describe('held for the account’s owner', () => {
    // A copy of the app on its own key: NoClick holds the purchase for the owner, and the dialog follows it.
    function openHeld() {
        const fake = fakeWork({ machineHosts: 'two' });
        const api = holding(fake.fetch, [{ method: 'POST', path: '/v1/machines' }]);
        const onBought = vi.fn<(machine: Machine) => void>();
        const live = createWorkLive();
        render(
            <WorkProviders client={workFixtureClient(api.fetch)} live={live}>
                <BuyMachine agent={{ name: 'Atlas', made: true }} onBought={onBought} onClose={() => undefined} />
            </WorkProviders>
        );
        return { fake, api, onBought, live };
    }

    it('says it went to the owner and where, never an error, and is bought once they approve it', async () => {
        const { fake, api, onBought, live } = openHeld();
        await toConfirm('Large');
        await unheld();
        await act(async () => fireEvent.click(buyButton()));
        const notice = await screen.findByTestId('held-call');
        expect(notice.textContent).toContain('Rent Large in Europe: waiting for approval');
        expect(notice.textContent).toContain('Sent to the account’s owner to approve, by email.');
        expect(screen.queryByRole('alert')).toBeNull();
        // Nothing was bought, and the link went to the owner, not this page.
        expect(fake.machines.filter((m) => m.name === 'atlas-box')).toEqual([]);
        expect(notice.querySelector('a')).toBeNull();
        expect(onBought).not.toHaveBeenCalled();

        const frame = await api.approve();
        act(() => live.deliver('platform:resource', frame));
        await waitFor(() => expect(onBought).toHaveBeenCalled());
        expect(onBought.mock.calls[0][0].name).toBe('atlas-box');
        expect(screen.getByText('Bought Large in Europe')).toBeTruthy();
    });

    it('says it wasn’t bought when the owner declines it', async () => {
        const { api, onBought, live } = openHeld();
        await toConfirm('Large');
        await unheld();
        await act(async () => fireEvent.click(buyButton()));
        await screen.findByTestId('held-call');
        act(() => live.deliver('platform:resource', api.decline()));
        await waitFor(() => expect(screen.getByTestId('held-call').getAttribute('data-phase')).toBe('declined'));
        expect(screen.getByTestId('held-call').textContent).toBe('Rent Large in Europe: not doneThe person declined it.');
        expect(onBought).not.toHaveBeenCalled();
    });
});
