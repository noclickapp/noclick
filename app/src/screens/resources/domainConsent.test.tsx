// @vitest-environment happy-dom
// Buying a domain as the app's key, through the platform API: the registrant's acceptance of the registration agreement
// is the moment its box was ticked and is sent only from that tick, never kept or ticked for them; the registrant on
// file shows only who it is; and none of what the buyer typed reaches an address, a log or the browser's storage.
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { NoClick } from 'noclick';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { BuyDomainPage } from './BuyDomainPage';
import { platformRegistrar } from './registrar';

vi.mock('sonner', () => ({ toast: { success: vi.fn() } }));

const OFFER = { object: 'domain_offer', name: 'acme.ai', available: true, price_usd: 160, renewal_usd: 150, premium: false, min_years: 2, max_years: 10, claims_notice: null };
const TYPED = { name: 'Ana Silva', email: 'ana@example.com', phone: '+14155550123', street: '500 Market St', city: 'San Francisco', postal: '94105' };
const ON_FILE = { name: 'Ana Silva', email: 'ana@example.com', phone: '+14155550123', address: '500 Market St', city: 'San Francisco', region: 'CA', postal_code: '94105', country: 'US', organization: 'Acme Corp', agreement_accepted_at: '2026-09-01T00:00:00Z' };

interface Sent {
    method: string;
    url: string;
    body: Record<string, unknown> | undefined;
}

let logged: string[];
/** What a log line says, an object's fields included. */
const said = (arg: unknown) => (typeof arg === 'string' ? arg : (JSON.stringify(arg) ?? String(arg)));
beforeEach(() => {
    // Radix's checkbox measures itself; happy-dom has no ResizeObserver.
    vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
    logged = [];
    for (const level of ['log', 'info', 'warn', 'error', 'debug'] as const) {
        vi.spyOn(console, level).mockImplementation((...args: unknown[]) => void logged.push(args.map(said).join(' ')));
    }
    localStorage.clear();
    sessionStorage.clear();
});
afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    vi.useRealTimers();
});

/** The page over the platform API's registrar, as Resources mounts it, the API answered here. */
function open(onFile: Record<string, unknown> | null): Sent[] {
    const sent: Sent[] = [];
    const fetch: typeof globalThis.fetch = async (input, init) => {
        const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url);
        const body = typeof init?.body === 'string' ? (JSON.parse(init.body) as Record<string, unknown>) : undefined;
        sent.push({ method: init?.method ?? 'GET', url: `${url.pathname}${url.search}`, body });
        const reply =
            url.pathname === '/v1/domains/search'
                ? { object: 'list', data: [OFFER], next_cursor: null }
                : url.pathname === '/v1/domains/agreement'
                  ? { url: 'https://noclick.test/legal/domains', version: '1' }
                  : url.pathname === '/v1/domains/registrant'
                    ? onFile
                    : url.pathname === '/v1/account'
                      ? { owner: {} }
                      : { object: 'operation', id: 'op_1', kind: 'domain.buy', status: 'running', price_usd: 160, domain_id: 'dom_1' };
        return new Response(JSON.stringify(reply), { status: 200, headers: { 'Content-Type': 'application/json' } });
    };
    const client = new NoClick({ apiKey: 'a-fixture-holds-no-key', baseUrl: 'https://api.test', fetch, maxRetries: 0 });
    render(
        <MemoryRouter>
            <BuyDomainPage registrar={platformRegistrar(client)} seed="acme" owned={[]} onBack={() => undefined} onBought={() => undefined} onOpen={() => undefined} />
        </MemoryRouter>
    );
    return sent;
}

async function checkout() {
    const row = await waitFor(() => screen.getAllByTestId('available-domain').find((r) => r.textContent?.includes('acme.ai'))!);
    fireEvent.click(within(row).getByRole('button', { name: 'Buy' }));
    return screen.findByRole('button', { name: 'Buy for $160.00' });
}

function fillDetails() {
    const fill = (label: string, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } });
    fill('Full name', TYPED.name);
    fill('Email', TYPED.email);
    fill('Phone', TYPED.phone);
    fill('Street address', TYPED.street);
    fill('City', TYPED.city);
    fill('State or region', 'CA');
    fill('Postal code', TYPED.postal);
    fill('Country (two letters)', 'us');
}

const purchases = (sent: Sent[]) => sent.filter((s) => s.method === 'POST' && s.url === '/v1/domains');

describe('the registration agreement, bought as a key', () => {
    it('is sent as accepted at the tick that accepted it, and only after that tick', async () => {
        vi.useFakeTimers({ toFake: ['Date'] });
        vi.setSystemTime(new Date('2026-10-01T09:00:00Z'));
        const sent = open(null);
        const buy = (await checkout()) as HTMLButtonElement;
        fillDetails();
        const box = screen.getByRole('checkbox', { name: /I accept the/ });
        // Not accepted for them: the box starts empty, and nothing is bought without it.
        expect(box.getAttribute('aria-checked')).toBe('false');
        expect(buy.disabled).toBe(true);
        // A tick that's taken back accepts nothing; the tick that stands is the one sent.
        fireEvent.click(box);
        fireEvent.click(box);
        vi.setSystemTime(new Date('2026-10-01T09:05:00Z'));
        fireEvent.click(box);
        vi.setSystemTime(new Date('2026-10-01T09:07:00Z'));
        await waitFor(() => expect(buy.disabled).toBe(false));
        await act(async () => fireEvent.click(buy));
        await waitFor(() => expect(purchases(sent)).toHaveLength(1));
        const registrant = purchases(sent)[0].body!.registrant as Record<string, unknown>;
        expect(registrant.agreement_accepted_at).toBe('2026-10-01T09:05:00.000Z');
    });

    it('keeps nothing of it, and opens unticked again', async () => {
        open(null);
        await checkout();
        fillDetails();
        fireEvent.click(screen.getByRole('checkbox', { name: /I accept the/ }));
        cleanup();
        expect(localStorage.length + sessionStorage.length).toBe(0);
        open(null);
        await checkout();
        expect(screen.getByRole('checkbox', { name: /I accept the/ }).getAttribute('aria-checked')).toBe('false');
    });

    it('puts none of what was typed in an address or a log', async () => {
        const sent = open(null);
        const buy = await checkout();
        fillDetails();
        fireEvent.click(screen.getByRole('checkbox', { name: /I accept the/ }));
        await waitFor(() => expect((buy as HTMLButtonElement).disabled).toBe(false));
        await act(async () => fireEvent.click(buy));
        await waitFor(() => expect(purchases(sent)).toHaveLength(1));
        const typed = Object.values(TYPED);
        const addresses = [...sent.map((s) => decodeURIComponent(s.url)), window.location.href];
        expect(addresses.filter((url) => typed.some((value) => url.includes(value)))).toEqual([]);
        expect(logged.filter((line) => typed.some((value) => line.includes(value)))).toEqual([]);
        expect(localStorage.length + sessionStorage.length).toBe(0);
    });
});

describe('the registrant on file', () => {
    it('shows who it is and nothing more of it', async () => {
        open(ON_FILE);
        await checkout();
        const shown = (await screen.findByTestId('registrant-on-file')).textContent!;
        // Its organization where it has one, else its name, and its email.
        expect(shown).toContain('Acme Corp (ana@example.com)');
        const page = document.body.textContent!;
        for (const kept of [ON_FILE.phone, ON_FILE.address, ON_FILE.city, ON_FILE.postal_code]) expect(page).not.toContain(kept);
    });
});
