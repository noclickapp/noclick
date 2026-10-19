// Resources › Numbers › Buy a number in the running app, with a fake transport:
// it opens on numbers for sale in the browser's own country (the fake sells in
// every country), each at its own price; Buy asks in place with what's charged
// now, Cancel backs out, and confirming buys exactly that number at exactly that
// price; a number whose country asks who holds it takes their name, address and
// a phone to reach them on first; numbers whose country asks for documents are
// listed under one note and can't be bought. The country picker is checked as
// laid out: names keep their room beside the longest line of kinds, and nothing
// scrolls sideways. Nothing reaches the provider or an account; preview() leaves the page
// mounted for visual checks.
import { createRoot } from 'react-dom/client';
import { createRoutesStub } from 'react-router';
import { flushSync } from 'react-dom';
import { getCountries } from 'libphonenumber-js';
import { BuyNumberPage } from '~/components/shell/resources/BuyNumberPage';
import { nc } from '~/lib/nc';

function offer(phone_number: string, locality: string, capabilities: string[], extra: Record<string, unknown> = {}) {
    return {
        phone_number, country: 'US', number_type: 'local', locality, region: 'CA', capabilities, monthly_credits: 4, upfront_credits: 4,
        requirements: { needs: 'none', items: [] }, texting: 'registration', ...extra,
    };
}

const NUMBERS = [
    offer('+14155550134', 'San Francisco', ['voice', 'SMS']),
    offer('+14155550187', 'San Francisco', ['voice', 'SMS', 'MMS']),
    offer('+14155551220', 'Oakland', ['voice']),
    offer('+5215512345678', '', ['voice'], {
        country: 'MX',
        number_type: 'mobile',
        region: '',
        texting: 'none',
        requirements: {
            needs: 'address',
            items: [
                { id: 'r-address', kind: 'address', name: 'Worldwide Physical Address', description: '', example: '', values: [] },
                { id: 'r-contact', kind: 'contact', name: 'Contact Information (Name, Business Name, Phone Number)', description: '', example: '', values: [] },
            ],
        },
    }),
];

// What a search in a country that asks a step that can't be taken here finds (India's requirements, as Telnyx lists them).
const INDIA_ASKS = {
    needs: 'steps',
    items: [
        { id: 'r-company', kind: 'step', name: 'Company Link (Approved Company Group UUID)', description: '', example: '', values: [] },
        { id: 'r-onfido', kind: 'step', name: 'Onfido Verification Link - End User', description: '', example: '', values: [] },
        { id: 'r-gst', kind: 'document', name: 'GST Registration Certificate', description: '', example: '', values: [] },
    ],
};
const DOCUMENTS = [
    offer('+911141234567', 'Delhi', ['voice'], { country: 'IN', region: '', texting: 'none', requirements: INDIA_ASKS }),
    offer('+912241234567', 'Mumbai', ['voice'], { country: 'IN', region: '', texting: 'none', requirements: INDIA_ASKS }),
];
// Argentina sells every kind, all but local needing documents: the longest line the picker shows.
const ALL_KINDS = ['local', 'mobile', 'toll_free', 'national', 'shared_cost'];

let cleanup: (() => void) | undefined;
let searchFinds = NUMBERS;

function mount(calls: Array<Record<string, unknown>>, bought: string[]) {
    cleanup?.();
    const host = document.createElement('div');
    host.id = 'buy-number-test';
    Object.assign(host.style, { position: 'fixed', inset: '0', zIndex: '9999', overflow: 'auto', background: 'hsl(var(--background))' });
    document.body.appendChild(host);
    const transport = async (payload: Record<string, unknown>) => {
        calls.push(payload);
        if (payload.event_name === 'phone_number:coverage') {
            return {
                countries: getCountries().map((country) =>
                    country === 'AR'
                        ? { country, number_types: ALL_KINDS, texting_types: [], documents_types: ALL_KINDS.slice(1), steps_types: [] }
                        : {
                              country,
                              number_types: ['local', 'mobile'],
                              texting_types: ['local'],
                              documents_types: [],
                              steps_types: country === 'IN' ? ['local', 'mobile'] : [],
                          }
                ),
            };
        }
        if (payload.event_name === 'phone_number:places') return { places: [{ kind: 'area_code', value: '415', region: 'CA' }] };
        if (payload.event_name === 'phone_number:search') return { numbers: searchFinds };
        if (payload.event_name === 'phone_number:buy') return { credential_id: 'cred-test', phone_number: payload.phone_number };
        return { error: 'unexpected event' };
    };
    const Page = () => <BuyNumberPage onBack={() => undefined} onBought={() => bought.push('done')} sendEvent={transport as never} />;
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

export async function preview({ documents = false } = {}) {
    searchFinds = documents ? DOCUMENTS : NUMBERS;
    mount([], []);
    await nc.wait.forElement('#buy-number-test [data-testid="available-number"]');
    return { mounted: true };
}

export function closePreview() {
    cleanup?.();
}

export default async function () {
    const calls: Array<Record<string, unknown>> = [];
    const bought: string[] = [];
    const host = mount(calls, bought);
    try {
        await nc.wait.forElement('#buy-number-test [data-testid="available-number"]');
        const rows = () => Array.from(host.querySelectorAll<HTMLElement>('[data-testid="available-number"]'));
        nc.assert.equal(rows().length, NUMBERS.length, 'every number from the search is listed');
        nc.assert.equal(calls[0]?.event_name, 'phone_number:coverage', 'the page opens on where numbers are sold');
        nc.assert.ok(calls.some((c) => c.event_name === 'phone_number:search'), 'then on a search');
        nc.assert.ok(rows()[0].textContent?.includes('$1.00/mo') ?? false, 'each row shows its own price, in dollars');
        nc.assert.ok(!host.querySelector('[data-testid="needs-documents"]'), 'numbers that need no documents say nothing of them');

        // The country picker, laid out for real: every name keeps its room beside the longest line of kinds, and
        // nothing scrolls sideways.
        Array.from(host.querySelectorAll('button')).find((b) => b.getAttribute('aria-label')?.startsWith('Country:'))!.click();
        await nc.wait.forElement('[role="listbox"]');
        const list = document.querySelector<HTMLElement>('[role="listbox"]')!;
        const search = list.parentElement!.querySelector('input')!;
        nc.dom.type(search, 'Arg');
        await nc.wait.ms(50);
        const argentina = list.querySelector<HTMLElement>('[role="option"]')!;
        const [name, detail] = Array.from(argentina.querySelectorAll<HTMLElement>('span.block'));
        nc.assert.equal(name?.textContent, 'Argentina', 'the name is its own line');
        // Layout sizes, not rects: the popover opens with a zoom that scales every rect.
        nc.assert.ok(name.clientWidth > 0 && name.clientWidth >= name.scrollWidth, 'and shows whole beside a long detail');
        nc.assert.ok(detail?.textContent?.includes('need documents') ?? false, 'the kinds that need documents say so');
        nc.assert.ok(detail.offsetTop > name.offsetTop, 'on a line under the name');
        nc.assert.ok(list.scrollWidth <= list.clientWidth, 'the list never scrolls sideways');
        nc.assert.ok(getComputedStyle(list).scrollbarWidth === 'thin', 'and wears the app’s scrollbar');
        nc.dom.type(search, '');
        await nc.wait.ms(50);
        nc.assert.ok(list.scrollWidth <= list.clientWidth, 'nor with every country listed');
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
        search.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
        await nc.wait.ms(50);

        const buyButton = (row: HTMLElement) => Array.from(row.querySelectorAll('button')).find((b) => b.textContent?.trim() === 'Buy');
        buyButton(rows()[1])!.click();
        await nc.wait.ms(50);
        const confirmButton = Array.from(rows()[1].querySelectorAll('button')).find((b) => b.textContent?.includes('Buy for'));
        nc.assert.ok(!!confirmButton, 'Buy asks in place, with the price');
        nc.assert.ok(rows()[1].textContent?.includes('$2.00 is charged now') ?? false, 'what is charged now, first month and setup');
        nc.assert.equal(calls.filter((c) => c.event_name === 'phone_number:buy').length, 0, 'nothing is bought before confirming');

        Array.from(rows()[1].querySelectorAll('button')).find((b) => b.textContent?.trim() === 'Cancel')!.click();
        await nc.wait.ms(50);
        nc.assert.ok(!!buyButton(rows()[1]), 'Cancel backs out to Buy');

        buyButton(rows()[2])!.click();
        await nc.wait.ms(50);
        Array.from(rows()[2].querySelectorAll('button')).find((b) => b.textContent?.includes('Buy for'))!.click();
        await nc.wait.ms(100);
        const purchases = calls.filter((c) => c.event_name === 'phone_number:buy');
        nc.assert.equal(purchases.length, 1, 'confirming buys once');
        nc.assert.equal(purchases[0]?.phone_number, NUMBERS[2].phone_number, 'it buys the number that was confirmed');
        nc.assert.equal(purchases[0]?.monthly_credits, 4, 'at the monthly price shown');
        nc.assert.equal(purchases[0]?.upfront_credits, 4, 'and the one-time price shown');
        nc.assert.equal(bought.length, 1, 'the page hands back after the purchase');
        nc.assert.ok(host.scrollWidth <= host.clientWidth, 'no horizontal overflow');

        nc.assert.ok(rows()[3].textContent?.includes('Needs the holder’s name, address and phone') ?? false, 'a number whose country asks who holds it says so');
        buyButton(rows()[3])!.click();
        await nc.wait.forElement('#buy-number-test [data-testid="requirements-step"]');
        const step = host.querySelector<HTMLElement>('[data-testid="requirements-step"]')!;
        const field = (label: string) => Array.from(step.querySelectorAll('label')).find((l) => l.textContent === label)!.control!;
        for (const [label, value] of [
            ['Full name', 'Ana López García'],
            ['Street address', 'Av. Reforma 1'],
            ['City', 'Ciudad de México'],
            ['Postal code', '06600'],
            ['Contact phone', '+52 55 1234 5678'],
        ]) {
            nc.dom.type(field(label), value);
        }
        await nc.wait.ms(50);
        Array.from(step.querySelectorAll('button')).find((b) => b.textContent?.includes('Buy for'))!.click();
        await nc.wait.ms(100);
        const held = calls.filter((c) => c.event_name === 'phone_number:buy')[1]?.holder as { name?: string; country?: string; phone?: string } | undefined;
        nc.assert.equal(held?.name, 'Ana López García', 'the purchase carries the holder’s name as written');
        nc.assert.equal(held?.phone, '+525512345678', 'and a phone to contact them on, in E.164');
        nc.assert.equal(held?.country, 'MX', 'with an address in the number’s country');

        // A country that asks a step that can't be taken here: said once, above its numbers, none of which can be bought.
        searchFinds = DOCUMENTS;
        const page = mount(calls, bought);
        await nc.wait.forElement('#buy-number-test [data-testid="needs-steps"]');
        const note = page.querySelectorAll<HTMLElement>('[data-testid="needs-steps"]');
        nc.assert.equal(note.length, 1, 'one note for the whole list');
        nc.assert.ok(note[0].textContent?.includes('an identity check at its own link') ?? false, 'in plain words');
        nc.assert.ok(note[0].textContent?.includes('Buying these numbers here isn’t available yet') ?? false, 'that can’t be done here yet');
        const listed = Array.from(page.querySelectorAll<HTMLElement>('[data-testid="available-number"]'));
        nc.assert.equal(listed.length, DOCUMENTS.length, 'the numbers are still listed');
        nc.assert.ok(listed.every((r) => r.querySelectorAll('button').length === 0 && (r.textContent?.includes('/mo') ?? false)), 'with their price and no Buy');
        return { listed: NUMBERS.length, bought: purchases[0]?.phone_number };
    } finally {
        searchFinds = NUMBERS;
        cleanup?.();
    }
}
