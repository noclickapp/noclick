// @vitest-environment jsdom
// Resources › Numbers › Buy a number over a fake transport: it opens on the person's own country, every filter reaches
// the search, each number shows its own price, a country that asks a step that can't be taken here says so once (in the
// picker, and above its numbers, none of which offers Buy), one that asks who holds it takes their name and address
// first (and a phone to reach them on, the account's own offered, where it asks for their contact information), one that
// asks for documents takes them too (uploaded once, offered again) and leaves the number in the carrier's review, a
// number the carrier sent back is corrected and resubmitted, a price that moved comes back to be agreed again, and
// nothing is bought before the in-row confirm with what's charged now.
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createRoutesStub } from 'react-router';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

const detected = vi.hoisted(() => ({ country: 'GB' as string | undefined }));
vi.mock('~/hooks/useDetectedCountry', () => ({ useDetectedCountry: () => detected.country }));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/utils/credentialAutoSelect', () => ({ invalidateCredentialsCache: vi.fn() }));
vi.mock('~/components/shell/AppShell', () => ({ useInPhoneShell: () => false, PhoneBarBack: () => null }));
vi.mock('sonner', () => ({ toast: { success: vi.fn() } }));
import { BuyNumberPage } from '~/components/shell/resources/BuyNumberPage';

const COVERAGE = [
    { country: 'US', number_types: ['local', 'toll_free'], texting_types: ['local'], documents_types: [], steps_types: [] },
    { country: 'GB', number_types: ['local', 'mobile'], texting_types: ['mobile'], documents_types: [], steps_types: [] },
    { country: 'DE', number_types: ['local'], texting_types: [], documents_types: ['local'], steps_types: [] },
    // Every kind in stock asks a step that can't be taken here; Mexico's local numbers do, its mobile ones don't.
    { country: 'IN', number_types: ['local', 'mobile'], texting_types: [], documents_types: [], steps_types: ['local', 'mobile'] },
    { country: 'MX', number_types: ['local', 'mobile'], texting_types: [], documents_types: [], steps_types: ['local'] },
];

function offer(phone_number: string, extra: Record<string, unknown> = {}) {
    return {
        phone_number, country: 'GB', number_type: 'local', locality: 'LONDON', region: '', capabilities: ['voice'],
        monthly_credits: 4, upfront_credits: 4, requirements: { needs: 'none', items: [] }, texting: 'none', ...extra,
    };
}

const LONDON = offer('+442071234567');
const LEEDS = offer('+441131234999', { locality: 'LEEDS' });
const asked = (id: string, kind: string, name: string, extra: Record<string, unknown> = {}) => ({ id, kind, name, description: '', example: '', values: [], ...extra });
// What a country that asks a step asks (India's, as Telnyx lists them).
const INDIA_ASKS = {
    needs: 'steps',
    items: [
        asked('r-company', 'step', 'Company Link (Approved Company Group UUID)'),
        asked('r-onfido', 'step', 'Onfido Verification Link - End User'),
        asked('r-gst', 'document', 'GST Registration Certificate'),
    ],
};
const DELHI = offer('+911141234567', { country: 'IN', locality: 'DELHI', requirements: INDIA_ASKS });
const MUMBAI = offer('+912241234567', { country: 'IN', locality: 'MUMBAI', requirements: INDIA_ASKS });
// What Telnyx asks of who holds a number like it: an address, and their contact information.
const CONTACT = asked('r-contact', 'contact', 'Contact Information (Name, Business Name, Phone Number)');
const ADDRESS = offer('+447700900123', { number_type: 'mobile', locality: '', capabilities: ['voice', 'SMS'], texting: 'unavailable',
    requirements: { needs: 'address', items: [asked('r-address', 'address', 'Worldwide Physical Address'), CONTACT] } });
// What Telnyx asks before it sells a German local number, in its words: an address in the area, which identity
// document, and a copy of it.
const GERMANY_ASKS = {
    needs: 'documents',
    items: [
        asked('r-area', 'address', 'Address Matching the DID Area Code', { description: 'An address in the area code of the number.' }),
        asked('r-type', 'textual', 'Identity Document Type', { values: ['Identity card', 'Passport'], description: 'The type of identity document.' }),
        asked('r-reg', 'textual', 'Company Registration Number', { example: 'HRB 12345' }),
        asked('r-id', 'document', 'Identity Document', { description: 'A copy of the holder’s identity document.' }),
    ],
};
const BERLIN = offer('+493012345678', { country: 'DE', locality: 'BERLIN', requirements: GERMANY_ASKS });
const PASSPORT = { id: 'doc-1', requirement_id: 'r-id', requirement_name: 'Identity Document', filename: 'passport.pdf', uploaded_at: '2026-10-01T10:00:00Z' };

let calls: Record<string, unknown>[];
let replies: Record<string, (payload: Record<string, unknown>) => unknown>;
const bought = vi.fn();

function mount() {
    const transport = async (payload: Record<string, unknown>) => {
        calls.push(payload);
        return replies[payload.event_name as string](payload);
    };
    const Page = () => <BuyNumberPage onBack={() => undefined} onBought={bought} sendEvent={transport as never} />;
    const App = createRoutesStub([{ path: '/', Component: Page }]);
    render(<App initialEntries={['/']} />);
}

const sent = (event: string) => calls.filter((c) => c.event_name === event);
const rows = () => screen.queryAllByTestId('available-number');

beforeEach(() => {
    calls = [];
    detected.country = 'GB';
    bought.mockReset();
    replies = {
        'phone_number:coverage': () => ({ countries: COVERAGE }),
        'phone_number:places': () => ({ places: [{ kind: 'locality', value: 'London', region: 'England' }, { kind: 'locality', value: 'Leeds', region: 'England' }] }),
        'phone_number:search': () => ({ numbers: [LONDON, LEEDS, ADDRESS] }),
        'phone_number:buy': (p) => ({ credential_id: 'cred-1', phone_number: p.phone_number }),
        'phone_number:orders': () => ({ orders: [] }),
        'phone_number:documents': () => ({ documents: [] }),
    };
});
afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
});

it('opens on the detected country and searches its local numbers', async () => {
    mount();
    await waitFor(() => expect(rows()).toHaveLength(3));
    expect(screen.getByRole('button', { name: 'Country: United Kingdom' })).toBeTruthy();
    expect(sent('phone_number:search')[0]).toMatchObject({ country: 'GB', number_type: 'local', features: 'voice', area_code: null, locality: null, contains: null });
    expect(sent('phone_number:places')[0]).toMatchObject({ country: 'GB', number_type: 'local' });
    // The country's own kinds are the choices.
    expect(screen.getByRole('radio', { name: 'Mobile' })).toBeTruthy();
    expect(screen.queryByRole('radio', { name: 'Toll-free' })).toBeNull();
});

it('lets an account short of the balance browse, and sends it to top up when it buys, never to a plan', async () => {
    replies['phone_number:buy'] = () => ({ error: 'The account needs at least $5 in its balance for phone numbers; it has $4.99.', kind: 'credits' });
    mount();
    await waitFor(() => expect(rows()).toHaveLength(3));
    fireEvent.click(within(rows()[0]).getByRole('button', { name: /^Buy/ }));
    fireEvent.click(within(rows()[0]).getByRole('button', { name: 'Buy for $2.00' }));
    const refused = await screen.findByRole('alert');
    expect(refused.textContent).toContain('needs at least $5 in its balance');
    expect(within(refused).getByRole('link', { name: 'Top up' }).getAttribute('href')).toBe('/dashboard?action=topup');
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(bought).not.toHaveBeenCalled();
});

it('opens on the US when nothing says where the person is, and says so when the country sells none', async () => {
    detected.country = undefined;
    mount();
    await waitFor(() => expect(sent('phone_number:search')).toHaveLength(1));
    expect(sent('phone_number:search')[0].country).toBe('US');
    cleanup();
    calls = [];
    detected.country = 'JP';
    mount();
    expect(await screen.findByTestId('not-sold')).toBeTruthy();
    expect(screen.getByTestId('not-sold').textContent).toContain('Japan');
    expect(sent('phone_number:search')).toHaveLength(0);
});

it('lists the countries with numbers in stock, the kinds that need documents or can’t be bought said so beside each name', async () => {
    globalThis.ResizeObserver ??= class {
        observe() {}
        unobserve() {}
        disconnect() {}
    } as unknown as typeof ResizeObserver;
    mount();
    await waitFor(() => expect(rows()).toHaveLength(3));
    fireEvent.click(screen.getByRole('button', { name: 'Country: United Kingdom' }));
    const list = screen.getByRole('listbox');
    expect(within(list).getAllByRole('option').map((o) => o.textContent)).toEqual([
        'United KingdomLocal, Mobile',
        'GermanyLocal · needs documents',
        'IndiaLocal, Mobile · not sold here yet',
        'MexicoMobile · Local not sold here yet',
        'United StatesLocal, Toll-free',
    ]);
    // A country whose kind can't be bought here opens on one that can be.
    fireEvent.click(within(list).getByRole('option', { name: /Mexico/ }));
    await waitFor(() => expect(sent('phone_number:search').at(-1)).toMatchObject({ country: 'MX', number_type: 'mobile' }));
});

it('says once, above the list, that a country asks a step that can’t be taken here, and offers none of its numbers', async () => {
    detected.country = 'IN';
    replies['phone_number:search'] = () => ({ numbers: [DELHI, MUMBAI] });
    mount();
    await waitFor(() => expect(rows()).toHaveLength(2));
    expect(sent('phone_number:search')[0]).toMatchObject({ country: 'IN', number_type: 'local' });
    const [note] = screen.getAllByTestId('needs-steps');
    expect(note.textContent).toContain('Buying these numbers here isn’t available yet');
    expect(note.textContent).toContain('such as an identity check at its own link');
    // The full list is behind a disclosure.
    const disclosure = note.querySelector('details')!;
    expect(disclosure.open).toBe(false);
    expect(within(note).getByText('What’s asked (3)')).toBeTruthy();
    expect(within(note).getAllByRole('listitem', { hidden: true }).map((li) => li.textContent)).toEqual(INDIA_ASKS.items.map((i) => i.name));
    for (const row of rows()) {
        expect(row.textContent).toContain('$1.00/mo'); // the number and its price stay
        expect(within(row).queryByRole('button')).toBeNull();
        expect(row.textContent).not.toContain('GST');
    }
    // A country that asks nothing of the sort says nothing of it.
    replies['phone_number:search'] = () => ({ numbers: [LONDON] });
    fireEvent.click(screen.getByRole('button', { name: 'Country: India' }));
    fireEvent.click(within(screen.getByRole('listbox')).getByRole('option', { name: /United Kingdom/ }));
    await waitFor(() => expect(rows()).toHaveLength(1));
    expect(screen.queryByTestId('needs-steps')).toBeNull();
    expect(within(rows()[0]).getByRole('button', { name: /^Buy/ })).toBeTruthy();
});

it('sends every filter: kind, a suggested place, digits and texts', async () => {
    mount();
    await waitFor(() => expect(rows()).toHaveLength(3));
    fireEvent.click(screen.getByRole('radio', { name: 'Mobile' }));
    await waitFor(() => expect(sent('phone_number:search').at(-1)).toMatchObject({ number_type: 'mobile' }));
    const place = screen.getByRole('combobox', { name: 'City, region or area code' });
    fireEvent.focus(place);
    fireEvent.change(place, { target: { value: 'Lo' } });
    fireEvent.mouseDown(await screen.findByRole('option', { name: /London/ }));
    await waitFor(() => expect(sent('phone_number:search').at(-1)).toMatchObject({ locality: 'London', number_type: 'mobile' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Digits or letters the number contains' }), { target: { value: '12-3' } });
    fireEvent.click(screen.getByRole('radio', { name: 'Calls and texts' }));
    await waitFor(() => expect(sent('phone_number:search').at(-1)).toMatchObject({ contains: '123', features: 'voice_sms', locality: 'London' }));
    // A typed area code (digits) goes as one; a region suggestion as a region.
    fireEvent.change(place, { target: { value: '20' } });
    fireEvent.click(screen.getByRole('button', { name: /Search/ }));
    await waitFor(() => expect(sent('phone_number:search').at(-1)).toMatchObject({ area_code: '20', locality: null }));
    fireEvent.focus(place);
    fireEvent.change(place, { target: { value: 'Eng' } });
    fireEvent.mouseDown(await screen.findByRole('option', { name: /England/ }));
    await waitFor(() => expect(sent('phone_number:search').at(-1)).toMatchObject({ region: 'England', area_code: null }));
});

it('shows each number formatted for its country with its own price, and who its country asks to hold it', async () => {
    mount();
    await waitFor(() => expect(rows()).toHaveLength(3));
    const [london, leeds, address] = rows();
    expect(london.textContent).toContain('+44 20 7123 4567');
    expect(london.textContent).toContain('London');
    expect(london.textContent).toContain('$1.00/mo');
    expect(london.textContent).toContain('+ $1.00 once');
    expect(leeds.textContent).toContain('Leeds');
    expect(address.textContent).toContain('Calls · Texts');
    expect(address.textContent).toContain('Needs the holder’s name, address and phone');
    expect(screen.queryByTestId('needs-documents')).toBeNull();
});

it('buys only after the in-row confirm, at exactly the price shown', async () => {
    mount();
    await waitFor(() => expect(rows()).toHaveLength(3));
    const london = rows()[0];
    fireEvent.click(within(london).getByRole('button', { name: /^Buy/ }));
    expect(london.textContent).toContain('$2.00 is charged now ($1.00 to set it up and the first month), then $1.00 every month');
    expect(sent('phone_number:buy')).toHaveLength(0);
    fireEvent.click(within(london).getByRole('button', { name: 'Buy for $2.00' }));
    await waitFor(() => expect(bought).toHaveBeenCalledTimes(1));
    expect(sent('phone_number:buy')).toEqual([
        { event_name: 'phone_number:buy', phone_number: '+442071234567', country: 'GB', number_type: 'local', monthly_credits: 4, upfront_credits: 4 },
    ]);
});

it('takes the holder’s name, address and contact phone for a country that asks who holds it, before buying', async () => {
    mount();
    await waitFor(() => expect(rows()).toHaveLength(3));
    fireEvent.click(within(rows()[2]).getByRole('button', { name: /^Buy/ }));
    const step = await screen.findByTestId('requirements-step');
    expect(step.textContent).toContain('NoClick files these details with the carrier');
    const buy = within(step).getByRole('button', { name: 'Buy for $2.00' }) as HTMLButtonElement;
    expect(buy.disabled).toBe(true);
    for (const [label, value] of [['Full name', 'Dana Ruiz'], ['Street address', '1 Pall Mall'], ['City', 'London'], ['Postal code', 'SW1Y 5LU']]) {
        fireEvent.change(within(step).getByLabelText(label), { target: { value } });
    }
    // Its contact information takes a phone too, and only a whole one.
    expect(buy.disabled).toBe(true);
    expect(step.textContent).toContain('Still needed: contact phone.');
    fireEvent.change(within(step).getByLabelText('Contact phone'), { target: { value: '+44 7400 1234' } });
    expect(buy.disabled).toBe(true);
    fireEvent.change(within(step).getByLabelText('Contact phone'), { target: { value: '+44 7400 123456' } });
    expect(buy.disabled).toBe(false);
    fireEvent.click(buy);
    await waitFor(() => expect(bought).toHaveBeenCalledTimes(1));
    expect(sent('phone_number:buy')[0].holder).toEqual({
        name: 'Dana Ruiz', business_name: null, street: '1 Pall Mall', street2: null, city: 'London', region: null, postal_code: 'SW1Y 5LU', country: 'GB',
        phone: '+447400123456',
    });
});

it('offers the account’s own verified phone as the contact phone', async () => {
    replies['phone_number:coverage'] = () => ({ countries: COVERAGE, contact_phone: '+12015550123' });
    mount();
    await waitFor(() => expect(rows()).toHaveLength(3));
    fireEvent.click(within(rows()[2]).getByRole('button', { name: /^Buy/ }));
    const step = await screen.findByTestId('requirements-step');
    expect((within(step).getByLabelText('Contact phone') as HTMLInputElement).value).toBe('+1 201 555 0123');
    for (const [label, value] of [['Full name', 'Dana Ruiz'], ['Street address', '1 Pall Mall'], ['City', 'London'], ['Postal code', 'SW1Y 5LU']]) {
        fireEvent.change(within(step).getByLabelText(label), { target: { value } });
    }
    fireEvent.click(within(step).getByRole('button', { name: 'Buy for $2.00' }));
    await waitFor(() => expect(bought).toHaveBeenCalledTimes(1));
    expect(sent('phone_number:buy')[0].holder).toMatchObject({ name: 'Dana Ruiz', phone: '+12015550123' });
});

it('asks no phone where the country asks only for an address', async () => {
    replies['phone_number:search'] = () => ({ numbers: [{ ...ADDRESS, requirements: { needs: 'address', items: [{ kind: 'address', name: 'Worldwide Physical Address', description: '' }] } }] });
    replies['phone_number:coverage'] = () => ({ countries: COVERAGE, contact_phone: '+12015550123' });
    mount();
    await waitFor(() => expect(rows()).toHaveLength(1));
    expect(rows()[0].textContent).toContain('Needs the holder’s name and address,');
    fireEvent.click(within(rows()[0]).getByRole('button', { name: /^Buy/ }));
    const step = await screen.findByTestId('requirements-step');
    expect(within(step).queryByLabelText('Contact phone')).toBeNull();
    for (const [label, value] of [['Full name', 'Dana Ruiz'], ['Street address', '1 Pall Mall'], ['City', 'London'], ['Postal code', 'SW1Y 5LU']]) {
        fireEvent.change(within(step).getByLabelText(label), { target: { value } });
    }
    fireEvent.click(within(step).getByRole('button', { name: 'Buy for $2.00' }));
    await waitFor(() => expect(bought).toHaveBeenCalledTimes(1));
    expect(sent('phone_number:buy')[0].holder).not.toHaveProperty('phone');
});

it('shows a price that moved and buys only when it is agreed to again', async () => {
    replies['phone_number:buy'] = () => ({ error: 'This number’s price changed since it was shown.', kind: 'price', monthly_credits: 6, upfront_credits: 4 });
    mount();
    await waitFor(() => expect(rows()).toHaveLength(3));
    fireEvent.click(within(rows()[0]).getByRole('button', { name: /^Buy/ }));
    fireEvent.click(within(rows()[0]).getByRole('button', { name: 'Buy for $2.00' }));
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(rows()[0].textContent).toContain('$1.50/mo');
    replies['phone_number:buy'] = (p) => ({ credential_id: 'cred-1', phone_number: p.phone_number });
    fireEvent.click(within(rows()[0]).getByRole('button', { name: 'Buy for $2.50' }));
    await waitFor(() => expect(bought).toHaveBeenCalledTimes(1));
    expect(sent('phone_number:buy').at(-1)).toMatchObject({ monthly_credits: 6, upfront_credits: 4 });
});

it('suggests loosening a search that found nothing', async () => {
    mount();
    await waitFor(() => expect(rows()).toHaveLength(3));
    replies['phone_number:search'] = () => ({ numbers: [] });
    fireEvent.change(screen.getByRole('textbox', { name: 'Digits or letters the number contains' }), { target: { value: '999' } });
    fireEvent.click(screen.getByRole('button', { name: /Search/ }));
    const empty = await screen.findByTestId('no-numbers');
    replies['phone_number:search'] = () => ({ numbers: [LONDON] });
    fireEvent.click(within(empty).getByRole('button', { name: 'Any digits' }));
    await waitFor(() => expect(rows()).toHaveLength(1));
    expect(sent('phone_number:search').at(-1)).toMatchObject({ contains: null });
    expect(screen.queryByTestId('no-numbers')).toBeNull(); // gone with the results
});

function fill(step: HTMLElement, fields: [string, string][]) {
    for (const [label, value] of fields) fireEvent.change(within(step).getByLabelText(label), { target: { value } });
}
const HOLDER: [string, string][] = [['Full name', 'Dana Ruiz'], ['Street address', 'Unter den Linden 1'], ['City', 'Berlin'], ['Postal code', '10117']];

it('takes each document and answer a country asks, uploads the file to its own link, and leaves the number in review', async () => {
    detected.country = 'DE';
    replies['phone_number:search'] = () => ({ numbers: [BERLIN] });
    replies['phone_number:document_upload'] = () => ({ upload_url_path: '/api/phone-numbers/documents?token=signed' });
    replies['phone_number:buy'] = (p) => ({ order_id: 'order-1', phone_number: p.phone_number, status: 'in_review' });
    const fetched = vi.fn(async () => ({ ok: true, json: async () => ({ document: PASSPORT }) }));
    vi.stubGlobal('fetch', fetched);
    mount();
    await waitFor(() => expect(rows()).toHaveLength(1));
    const [note] = screen.getAllByTestId('needs-documents');
    expect(note.textContent).toContain('You add them when you buy one, and the carrier reviews them before it’s yours.');
    expect(rows()[0].textContent).toContain('Needs documents, added when you buy it');
    fireEvent.click(within(rows()[0]).getByRole('button', { name: /^Buy/ }));
    const step = await screen.findByTestId('requirements-step');
    expect(step.textContent).toContain('Germany asks for documents before a number is sold. The carrier reviews them');
    expect(step.textContent).toContain('Nothing is charged until the carrier approves the documents.');
    // One section per thing asked, each with the carrier's description behind "What's this".
    expect(within(step).getByRole('heading', { name: 'Who holds the number' })).toBeTruthy();
    const typeSection = within(step).getByRole('heading', { name: 'Identity Document Type' }).closest('section')!;
    expect(typeSection.textContent).toContain('What’s this');
    expect(typeSection.querySelector('details')!.textContent).toContain('The type of identity document.');
    // A choice where the carrier lists the answers, the carrier's example as the hint otherwise.
    const choice = within(typeSection).getByLabelText('Identity Document Type') as HTMLSelectElement;
    expect([...choice.options].map((o) => o.value)).toEqual(['', 'Identity card', 'Passport']);
    expect((within(step).getByLabelText('Company Registration Number') as HTMLInputElement).placeholder).toBe('e.g. HRB 12345');
    const submit = within(step).getByRole('button', { name: 'Submit for review' }) as HTMLButtonElement;
    fill(step, HOLDER);
    fireEvent.change(choice, { target: { value: 'Passport' } });
    fireEvent.change(within(step).getByLabelText('Company Registration Number'), { target: { value: 'HRB 99' } });
    expect(submit.disabled).toBe(true);
    expect(step.textContent).toContain('Still needed: a file for Identity Document.');
    // The file goes straight to the backend at the link signed for it; the purchase names it by id.
    const file = new File(['%PDF-1.4'], 'passport.pdf', { type: 'application/pdf' });
    fireEvent.change(within(step).getByLabelText('Upload Identity Document'), { target: { files: [file] } });
    await waitFor(() => expect(within(step).getByText('passport.pdf')).toBeTruthy());
    expect(sent('phone_number:document_upload')[0]).toMatchObject({ country: 'DE', number_type: 'local', requirement_id: 'r-id' });
    expect(fetched).toHaveBeenCalledWith(expect.stringMatching(/\/api\/phone-numbers\/documents\?token=signed&filename=passport\.pdf$/), expect.objectContaining({ method: 'POST', body: file }));
    expect(submit.disabled).toBe(false);
    replies['phone_number:orders'] = () => ({ orders: [{ id: 'order-1', phone_number: BERLIN.phone_number, country: 'DE', number_type: 'local', status: 'in_review', reason: null, deadline: null, monthly_credits: 4, upfront_credits: 4, credential_id: null, created_at: '' }] });
    fireEvent.click(submit);
    await waitFor(() => expect(screen.getByTestId('number-orders')).toBeTruthy());
    expect(sent('phone_number:buy')[0]).toMatchObject({
        phone_number: BERLIN.phone_number,
        holder: { name: 'Dana Ruiz', street: 'Unter den Linden 1', city: 'Berlin', postal_code: '10117', country: 'DE' },
        answers: { 'r-type': 'Passport', 'r-reg': 'HRB 99', 'r-id': 'doc-1' },
    });
    // In review: nothing bought yet, and it's listed as such above the search.
    expect(bought).not.toHaveBeenCalled();
    expect(screen.getByTestId('number-order').textContent).toContain('The carrier is reviewing its documents');
});

it('offers a document filed before for the next number, and removes one', async () => {
    detected.country = 'DE';
    replies['phone_number:search'] = () => ({ numbers: [BERLIN] });
    replies['phone_number:documents'] = () => ({ documents: [PASSPORT] });
    replies['phone_number:document_remove'] = () => ({ id: 'doc-1', removed: true, kept_by_carrier: true });
    mount();
    await waitFor(() => expect(rows()).toHaveLength(1));
    fireEvent.click(within(rows()[0]).getByRole('button', { name: /^Buy/ }));
    const step = await screen.findByTestId('requirements-step');
    const kept = (await within(step).findByRole('radio')) as HTMLInputElement;
    await waitFor(() => expect(kept.checked).toBe(true)); // chosen until another is picked
    expect(step.textContent).not.toContain('a file for Identity Document');
    fireEvent.click(within(step).getByRole('button', { name: 'Remove passport.pdf' }));
    await waitFor(() => expect(within(step).queryByRole('radio')).toBeNull());
    expect(sent('phone_number:document_remove')[0]).toMatchObject({ document_id: 'doc-1' });
    await waitFor(() => expect(step.textContent).toContain('The carrier keeps its copy on file for the number it was filed for.'));
    expect(step.textContent).toContain('a file for Identity Document');
});

it('shows a number the carrier sent back with its reason, and resubmits it corrected', async () => {
    const rejected = {
        id: 'order-9', phone_number: BERLIN.phone_number, country: 'DE', number_type: 'local', status: 'rejected',
        reason: 'The passport scan is cut off.', deadline: null, monthly_credits: 4, upfront_credits: 4, credential_id: null, created_at: '',
        requirements: GERMANY_ASKS,
    };
    replies['phone_number:orders'] = () => ({ orders: [rejected] });
    replies['phone_number:documents'] = () => ({ documents: [PASSPORT] });
    replies['phone_number:resubmit'] = () => ({ order: { ...rejected, status: 'in_review', reason: null } });
    mount();
    const listed = await screen.findByTestId('number-order');
    expect(listed.textContent).toContain('Changes needed: The passport scan is cut off.');
    fireEvent.click(within(listed).getByRole('button', { name: 'Fix and resubmit' }));
    const step = await screen.findByTestId('requirements-step');
    expect(within(step).getByTestId('sent-back').textContent).toContain('“The passport scan is cut off.”');
    fill(step, HOLDER);
    fireEvent.change(within(step).getByLabelText('Identity Document Type'), { target: { value: 'Identity card' } });
    fireEvent.change(within(step).getByLabelText('Company Registration Number'), { target: { value: 'HRB 99' } });
    await within(step).findByRole('radio');
    replies['phone_number:orders'] = () => ({ orders: [{ ...rejected, status: 'in_review', reason: null }] });
    fireEvent.click(within(step).getByRole('button', { name: 'Resubmit' }));
    await waitFor(() => expect(screen.queryByTestId('requirements-step')).toBeNull());
    expect(sent('phone_number:resubmit')[0]).toMatchObject({ order_id: 'order-9', answers: { 'r-type': 'Identity card', 'r-reg': 'HRB 99', 'r-id': 'doc-1' } });
    await waitFor(() => expect(screen.getByTestId('number-order').textContent).toContain('The carrier is reviewing its documents'));
});
