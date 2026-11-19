// Resources' registrar over a fake transport: what each step sends the
// platform API, and how its answers read on the buy page. Nothing reaches a
// registrar.
import { describe, expect, it } from 'vitest';
import { DomainRegistrarError, type DomainOffer } from '@/screens/domains/useDomainPurchase';
import { NoClick } from 'noclick';
import { DOMAIN_ENDINGS, platformRegistrar } from './registrar';

interface Sent {
    method: string;
    path: string;
    query: URLSearchParams;
    body: unknown;
    user: string | null;
}

type Reply = { status: number; body: unknown };

function transport(answer: (sent: Sent) => Reply, options?: Parameters<typeof platformRegistrar>[1]) {
    const sent: Sent[] = [];
    const fetch: typeof globalThis.fetch = async (input, init) => {
        const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url);
        const headers = new Headers(init?.headers);
        const request: Sent = {
            method: init?.method ?? 'GET',
            path: url.pathname,
            query: url.searchParams,
            body: typeof init?.body === 'string' ? JSON.parse(init.body) : undefined,
            user: headers.get('NoClick-User'),
        };
        sent.push(request);
        const reply = answer(request);
        return new Response(JSON.stringify(reply.body), { status: reply.status, headers: { 'Content-Type': 'application/json' } });
    };
    const client = new NoClick({ apiKey: 'test-token', baseUrl: 'https://api.test', fetch, maxRetries: 0 });
    return { registrar: platformRegistrar(client, options), sent };
}

const ok = (body: unknown): Reply => ({ status: 200, body });
const refused = (status: number, type: string, message: string, extra: Record<string, unknown> = {}): Reply => ({ status, body: { error: { type, message, ...extra } } });

const offer = (name: string, price: number | null, extra: Record<string, unknown> = {}) => ({
    object: 'domain_offer',
    name,
    available: price !== null,
    price_usd: price,
    renewal_usd: price,
    premium: false,
    min_years: price !== null ? 1 : null,
    max_years: price !== null ? 10 : null,
    claims_notice: null,
    ...extra,
});

describe('searching', () => {
    it('asks for the name on every ending, the asked one first, for the account', async () => {
        const { registrar, sent } = transport(() => ok({ object: 'list', data: [], next_cursor: null }));
        await registrar.search({ name: 'acme', ending: 'io' });
        const [search] = sent;
        expect(search.method).toBe('GET');
        expect(search.path).toBe('/v1/domains/search');
        expect(search.query.get('q')).toBe('acme');
        expect(search.query.get('tlds')?.split(',')).toEqual(['io', ...DOMAIN_ENDINGS.filter((e) => e !== 'io')]);
        expect(search.user).toBeNull();
    });

    it('lists the free endings in that order, then a few close names, priced for their term', async () => {
        const { registrar } = transport(() =>
            ok({
                object: 'list',
                data: [
                    offer('acme.com', null),
                    offer('acme.ai', 160, { min_years: 2, renewal_usd: 150 }),
                    offer('acme.io', 45),
                    offer('getacme.com', 12.99),
                    offer('acmehq.com', 11.5, { premium: true }),
                    offer('tryacme.com', null),
                ],
                next_cursor: null,
            })
        );
        const found = await registrar.search({ name: 'acme', ending: null });
        expect(found.asked).toEqual({ domain: 'acme.com', status: 'taken' });
        expect(found.offers.map((o) => o.domain)).toEqual(['acme.ai', 'acme.io', 'getacme.com', 'acmehq.com']);
        expect(found.offers[0]).toEqual({ domain: 'acme.ai', ending: 'ai', priceUsd: 160, years: 2, renewalUsd: 150 });
        expect(found.offers[2]).toMatchObject({ domain: 'getacme.com', ending: 'com', close: true });
        expect(found.offers[3].premium).toBe(true);
    });

    it('says the asked domain is available when it is, and carries a trademark notice', async () => {
        const { registrar } = transport(() => ok({ object: 'list', data: [offer('northwind.dev', 15, { claims_notice: 'A notice.' })], next_cursor: null }));
        const found = await registrar.search({ name: 'northwind', ending: 'dev' });
        expect(found.asked).toEqual({ domain: 'northwind.dev', status: 'available' });
        expect(found.offers[0].claimsNotice).toBe('A notice.');
    });

    it('reads a deployment with no registrar as domains being unavailable, and no plan refusal as a plan to sell', async () => {
        const off = transport(() => refused(409, 'not_available', "Domains aren't enabled on this deployment yet.", { next_step: 'Ask NoClick support.' }));
        await expect(off.registrar.search({ name: 'acme', ending: null })).rejects.toMatchObject({ kind: 'unavailable', message: "Domains aren't enabled on this deployment yet. Ask NoClick support." });
        // Domains are on every plan: a plan refusal from elsewhere in the API reads in its own words, with no upgrade.
        const free = transport(() => refused(402, 'plan_required', 'The platform API needs a paid plan.', { plans: ['member'], next_step: 'Upgrade the plan.' }));
        const error = await free.registrar.search({ name: 'acme', ending: null }).catch((e: unknown) => e);
        expect(error).toBeInstanceOf(DomainRegistrarError);
        expect(error).toMatchObject({ kind: undefined, message: 'The platform API needs a paid plan. Upgrade the plan.' });
    });
});

describe('checking out', () => {
    it('reads the agreement and the registrant on file', async () => {
        const { registrar, sent } = transport(({ path }) =>
            path === '/v1/domains/agreement'
                ? ok({ url: 'https://noclick.test/legal/domains', version: '2026-09' })
                : ok({ name: 'Ana Silva', email: 'ana@example.com', phone: '+14155550123', address: '500 Market St', city: 'San Francisco', region: 'CA', postal_code: '94105', country: 'US', organization: 'Acme Corp', agreement_accepted_at: '2026-09-01T00:00:00Z' })
        );
        expect(await registrar.checkout()).toEqual({ agreementUrl: 'https://noclick.test/legal/domains', onFile: { name: 'Ana Silva', email: 'ana@example.com', organization: 'Acme Corp' } });
        expect(sent.map((s) => s.path).sort()).toEqual(['/v1/domains/agreement', '/v1/domains/registrant']);
    });

    it('asks for details when nobody is on file, or when the one on file never accepted the agreement', async () => {
        const account = ok({ object: 'account', email: 'ana@example.com', owner: { email: 'ana@example.com' } });
        const none = transport(({ path }) => (path === '/v1/domains/agreement' ? ok({ url: 'https://noclick.test/a', version: '1' }) : path === '/v1/account' ? account : ok(null)));
        expect((await none.registrar.checkout()).onFile).toBeNull();
        const unaccepted = transport(({ path }) =>
            path === '/v1/domains/agreement'
                ? ok({ url: 'https://noclick.test/a', version: '1' })
                : path === '/v1/account'
                  ? account
                  : ok({ name: 'Ana Silva', email: 'ana@example.com', phone: '+1', address: 'x', city: 'y', region: 'z', postal_code: '1', country: 'US' })
        );
        expect((await unaccepted.registrar.checkout()).onFile).toBeNull();
    });

    it("starts the details, with nobody on file, from what NoClick knows of the owner, so they type only their address", async () => {
        const owner = { name: 'Ana Silva', email: 'ana@example.com', phone: '+14155550123' };
        const { registrar, sent } = transport(({ path }) =>
            path === '/v1/domains/agreement' ? ok({ url: 'https://noclick.test/a', version: '1' }) : path === '/v1/account' ? ok({ object: 'account', owner }) : ok(null)
        );
        expect(await registrar.checkout()).toEqual({ agreementUrl: 'https://noclick.test/a', onFile: null, known: owner });
        expect(sent.find((s) => s.path === '/v1/account')?.user).toBeNull();
    });
});

describe('buying', () => {
    const AI: DomainOffer = { domain: 'acme.ai', ending: 'ai', priceUsd: 160, years: 2, renewalUsd: 150 };
    const purchase = ok({ object: 'operation', id: 'op_1', kind: 'domain.buy', status: 'running', price_usd: 160, domain_id: 'dom_1' });

    it("buys the offer for the account at its term, never above the price shown, with the registrant's details and acceptance", async () => {
        const { registrar, sent } = transport(() => purchase);
        const acceptedAt = new Date('2026-10-09T12:00:00Z');
        await registrar.buy(AI, {
            registrant: { name: 'Ana Silva', email: 'ana@example.com', phone: '+14155550123', address: '500 Market St', city: 'San Francisco', region: 'CA', postalCode: '94105', country: 'US', agreementAcceptedAt: acceptedAt },
            acceptClaims: true,
        });
        expect(sent).toHaveLength(1);
        expect(sent[0]).toMatchObject({ method: 'POST', path: '/v1/domains', user: null });
        expect(sent[0].body).toEqual({
            name: 'acme.ai',
            max_price_usd: 160,
            years: 2,
            auto_renew: true,
            accept_claims: true,
            registrant: {
                name: 'Ana Silva',
                email: 'ana@example.com',
                phone: '+14155550123',
                address: '500 Market St',
                city: 'San Francisco',
                postal_code: '94105',
                country: 'US',
                region: 'CA',
                agreement_accepted_at: acceptedAt.toISOString(),
            },
        });
    });

    it('tells whoever asked the purchase’s operation once it’s placed, and nothing when it’s refused', async () => {
        const heard: string[] = [];
        await transport(() => purchase, { onPurchase: (id) => heard.push(id) }).registrar.buy(AI, { acceptClaims: false });
        expect(heard).toEqual(['op_1']);
        const taken = transport(() => refused(409, 'not_available', 'acme.ai is taken.'), { onPurchase: (id) => heard.push(id) });
        await expect(taken.registrar.buy(AI, { acceptClaims: false })).rejects.toBeInstanceOf(DomainRegistrarError);
        expect(heard).toEqual(['op_1']);
    });

    it('leaves the registrant out to use the one on file, and claims out when there was no notice', async () => {
        const { registrar, sent } = transport(() => purchase);
        await registrar.buy(AI, { acceptClaims: false });
        expect(sent[0].body).toEqual({ name: 'acme.ai', max_price_usd: 160, years: 2, auto_renew: true });
    });

    it('says when the price rose past what was shown, and when the balance can’t pay', async () => {
        const rose = transport(() => refused(402, 'price_exceeded', 'acme.ai costs $170.00 for 2 years, above max_price_usd ($160.00).', { price_usd: 170 }));
        await expect(rose.registrar.buy(AI, { acceptClaims: false })).rejects.toMatchObject({
            message: 'acme.ai now costs $170.00, more than the price you saw. Search again to see the new price.',
            kind: undefined,
        });
        const broke = transport(() => refused(402, 'payment_required', 'Your balance can’t cover this.', { next_step: 'Add credits.' }));
        await expect(broke.registrar.buy(AI, { acceptClaims: false })).rejects.toMatchObject({ kind: 'credits', message: 'Your balance can’t cover this. Add credits.' });
    });

    it('reads a refusal about the name itself as the name’s, not as domains being unavailable', async () => {
        const taken = transport(() => refused(409, 'not_available', 'acme.ai is taken.', { next_step: 'Search for another name.' }));
        await expect(taken.registrar.buy(AI, { acceptClaims: false })).rejects.toMatchObject({ kind: undefined, message: 'acme.ai is taken. Search for another name.' });
    });
});
