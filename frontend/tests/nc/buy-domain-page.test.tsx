// Resources › Domains › Buy a domain in the running app, with a fake registrar:
// the page opens on the name your domains have, says when that name is already
// yours, an ending chip searches the name on that ending, Buy opens a checkout
// with the price and term, Back leaves it, details entered with the agreement
// accepted let it buy, and confirming buys exactly that domain, once. Nothing
// reaches a registrar; preview() leaves the page mounted for visual checks.
import { createRoot } from 'react-dom/client';
import { createRoutesStub } from 'react-router';
import { flushSync } from 'react-dom';
import { BuyDomainPage } from '~/components/shell/resources/BuyDomainPage';
import type { DomainOffer, DomainPurchaseDetails, DomainQuery, DomainRegistrar } from '~/hooks/useDomainPurchase';
import { nc } from '~/lib/nc';

const ENDINGS = [
    { ending: 'com', priceUsd: 12.99, years: 1 },
    { ending: 'ai', priceUsd: 160, years: 2 },
    { ending: 'io', priceUsd: 45, years: 1 },
];

type Call = { search: DomainQuery } | { buy: DomainOffer; details: DomainPurchaseDetails };

let cleanup: (() => void) | undefined;

function mount(calls: Call[], log: string[]) {
    cleanup?.();
    const host = document.createElement('div');
    host.id = 'buy-domain-test';
    Object.assign(host.style, { position: 'fixed', inset: '0', zIndex: '9999', overflow: 'auto', background: 'hsl(var(--background))' });
    document.body.appendChild(host);
    const registrar: DomainRegistrar = {
        endings: ENDINGS.map((e) => e.ending),
        async search(query) {
            calls.push({ search: query });
            const wanted = query.ending ?? 'com';
            const offers: DomainOffer[] = ENDINGS.map((e) => ({ ...e, domain: `${query.name}.${e.ending}`, renewalUsd: e.priceUsd }));
            offers.sort((a, b) => Number(b.ending === wanted) - Number(a.ending === wanted));
            return {
                asked: { domain: `${query.name}.${wanted}`, status: 'taken' },
                offers: [...offers, { ...ENDINGS[0], domain: `get${query.name}.com`, renewalUsd: 12.99, close: true }],
            };
        },
        async checkout() {
            return { agreementUrl: 'https://noclick.com/legal/domain-registration', onFile: null };
        },
        async buy(offer, details) {
            calls.push({ buy: offer, details });
        },
    };
    const Page = () => (
        <BuyDomainPage seed="acme" owned={['acme.com']} registrar={registrar} onBack={() => undefined} onBought={(d) => log.push(`bought ${d}`)} onOpen={(d) => log.push(`open ${d}`)} />
    );
    const App = createRoutesStub([{ path: '/', Component: Page }]);
    const root = createRoot(host);
    flushSync(() => root.render(<App initialEntries={['/']} />));
    cleanup = () => {
        root.unmount();
        host.remove();
        cleanup = undefined;
    };
    return host;
}

export async function preview() {
    mount([], []);
    await nc.wait.forElement('#buy-domain-test [data-testid="available-domain"]');
    return { mounted: true };
}

export function closePreview() {
    cleanup?.();
}

const button = (root: ParentNode, match: (text: string) => boolean) => Array.from(root.querySelectorAll('button')).find((b) => match(b.textContent?.trim() ?? ''));

function type(host: HTMLElement, id: string, value: string) {
    const input = host.querySelector<HTMLInputElement>(`#${id}`)!;
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
    setter.call(input, value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
}

export default async function () {
    const calls: Call[] = [];
    const log: string[] = [];
    const host = mount(calls, log);
    try {
        await nc.wait.forElement('#buy-domain-test [data-testid="available-domain"]');
        const rows = () => Array.from(host.querySelectorAll<HTMLElement>('[data-testid="available-domain"]'));
        nc.assert.ok('search' in calls[0] && calls[0].search.name === 'acme' && calls[0].search.ending === null, 'the page opens on the name you already have');
        nc.assert.equal(rows().length, 3, 'the free endings and the close name are listed, never the one you own');
        nc.assert.ok(rows()[0].textContent?.includes('$160.00 for 2 years') ?? false, 'an offer is priced for its term');
        nc.assert.ok(rows()[2].textContent?.includes('A close name') ?? false, 'a close name says so');

        const asked = host.querySelector<HTMLElement>('[data-testid="asked-domain"]');
        nc.assert.ok(asked?.textContent?.includes('acme.com is already yours') ?? false, 'the name you own is named, not offered');
        button(asked!, (t) => t === 'Open it')!.click();
        nc.assert.equal(log.at(-1), 'open acme.com', 'Open it goes to the domain you own');

        button(host, (t) => t === '.io')!.click();
        await nc.wait.until(() => rows()[0]?.textContent?.includes('acme.io') ?? false, 2000);
        const last = calls.at(-1);
        nc.assert.ok(!!last && 'search' in last && last.search.ending === 'io', 'an ending chip searches the name on that ending');
        nc.assert.equal((host.querySelector('input') as HTMLInputElement).value, 'acme.io', 'the search box says what was searched');

        button(rows()[1], (t) => t === 'Buy')!.click();
        await nc.wait.until(() => !!button(host, (t) => t === 'Buy for $160.00'), 2000);
        nc.assert.equal(calls.filter((c) => 'buy' in c).length, 0, 'nothing is bought before confirming');
        button(host, (t) => t === 'Back')!.click();
        await nc.wait.until(() => rows().length === 3, 2000);

        button(rows()[0], (t) => t === 'Buy')!.click();
        await nc.wait.until(() => !!host.querySelector('#registrant-name'), 2000);
        const buy = () => button(host, (t) => t === 'Buy for $45.00')!;
        for (const [id, value] of [
            ['registrant-name', 'Ana Silva'],
            ['registrant-email', 'ana@example.com'],
            ['registrant-phone', '+14155550123'],
            ['registrant-address', '500 Market St'],
            ['registrant-city', 'San Francisco'],
            ['registrant-region', 'CA'],
            ['registrant-postalCode', '94105'],
            ['registrant-country', 'US'],
        ] as const)
            type(host, id, value);
        await nc.wait.ms(50);
        nc.assert.ok(buy().disabled, 'nothing is bought until the agreement is accepted');
        host.querySelector<HTMLButtonElement>('#registrant-agreement')!.click();
        await nc.wait.until(() => !buy().disabled, 2000);
        buy().click();
        await nc.wait.until(() => log.some((l) => l.startsWith('bought')), 2000);
        const purchases = calls.filter((c): c is Extract<Call, { buy: DomainOffer }> => 'buy' in c);
        nc.assert.equal(purchases.length, 1, 'confirming buys once');
        nc.assert.equal(purchases[0].buy.domain, 'acme.io', 'it buys the domain that was confirmed');
        nc.assert.equal(purchases[0].details.registrant?.name, 'Ana Silva', 'it registers the domain to the details entered');
        nc.assert.ok(purchases[0].details.registrant?.agreementAcceptedAt instanceof Date, 'with when the agreement was accepted');
        nc.assert.equal(log.at(-1), 'bought acme.io', 'the page hands back after the purchase');
        return { listed: 3, bought: purchases[0].buy.domain };
    } finally {
        cleanup?.();
    }
}
