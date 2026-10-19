// @vitest-environment jsdom
// Exercise the shared phone form's owner-confirmation mode. Selecting a number
// must only prepare a quote; a separate explicit click authorizes its purchase.
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, expect, it, vi } from 'vitest';

vi.mock('~/hooks/useDetectedCountry', () => ({ useDetectedCountry: () => 'US' }));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/utils/credentialAutoSelect', () => ({ invalidateCredentialsCache: vi.fn() }));
import { OrderReview, PhoneNumberPurchaseForm } from '~/components/credential/PhoneNumberPurchaseForm';

const quote = {
    id: 'server-quote', phone_number: '+15674833618', country: 'US', number_type: 'local' as const, locality: 'Lucas', region: 'OH',
    capabilities: ['voice'], requirements: { needs: 'none' as const, items: [] }, texting: 'none' as const,
    monthly_credits: 4, upfront_credits: 4, expires_at: '2099-01-01T00:00:00Z',
};
const offer = { ...quote, monthly_credits: 4, upfront_credits: 4 };
// The account's own verified phone comes with where numbers are sold, offered as a holder's contact phone.
const COVERAGE = { countries: [{ country: 'US', number_types: ['local'], texting_types: ['local'], documents_types: [], steps_types: [] }], contact_phone: '+31612345670' };
afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
});
const asked = (id: string, kind: 'address' | 'contact' | 'textual' | 'document' | 'step', name: string, extra: Record<string, unknown> = {}) => ({
    id, kind, name, description: '', example: '', values: [] as string[], ...extra,
});

function transport(rest: (event: Record<string, unknown>) => unknown, numbers: unknown[] = [offer]) {
    return vi.fn(async (event: Record<string, unknown>) => {
        if (event.event_name === 'phone_number:coverage') return COVERAGE;
        if (event.event_name === 'phone_number:places') return { places: [] };
        if (event.event_name === 'phone_number:search') return { numbers };
        return rest(event);
    });
}

it('offers nothing to review where the numbers ask a step that can’t be taken here, and says so once', async () => {
    const asks = { needs: 'steps' as const, items: [asked('r-1', 'step', 'Onfido Verification Link - End User')] };
    const send = transport(() => ({}), [{ ...offer, requirements: asks }, { ...offer, phone_number: '+15674833619', requirements: asks }]);
    render(<MemoryRouter><PhoneNumberPurchaseForm sendEvent={send} onCredentialCreated={vi.fn()} confirmation={{ onState: vi.fn() }} /></MemoryRouter>);
    const note = await screen.findByTestId('needs-steps');
    expect(note.textContent).toContain('Buying these numbers here isn’t available yet');
    expect(screen.getAllByTestId('available-number')).toHaveLength(2);
    expect(screen.queryByRole('button', { name: /^Review/ })).toBeNull();
    expect(send.mock.calls.some((c) => c[0].event_name === 'phone_number:quote')).toBe(false);
});

it('reviews the selected number and what it charges before confirming only the quote id', async () => {
    let finish: (value: unknown) => void = () => {};
    const send = transport((event) => (event.event_name === 'phone_number:quote' ? { quote } : new Promise((resolve) => { finish = resolve; })));
    const created = vi.fn();
    render(<MemoryRouter><PhoneNumberPurchaseForm sendEvent={send} onCredentialCreated={created} confirmation={{ onState: vi.fn() }} /></MemoryRouter>);
    fireEvent.click(await screen.findByRole('button', { name: /^Review/ }));
    const confirm = await screen.findByRole('button', { name: /Confirm purchase · \$2\.00/ });
    expect(screen.getByText('Renews monthly')).toBeTruthy();
    expect(screen.getByText('Of which, one-time setup')).toBeTruthy();
    expect(screen.getByText(/Call usage is billed separately/)).toBeTruthy();
    expect(send.mock.calls.map((c) => c[0].event_name)).toEqual(['phone_number:coverage', 'phone_number:search', 'phone_number:places', 'phone_number:quote']);
    expect(send.mock.calls[3][0]).toEqual({ event_name: 'phone_number:quote', phone_number: quote.phone_number, country: 'US', number_type: 'local' });
    fireEvent.click(confirm); fireEvent.click(confirm);
    expect(send.mock.calls.filter((c) => c[0].event_name === 'phone_number:confirm')).toHaveLength(1);
    expect(send).toHaveBeenLastCalledWith({ event_name: 'phone_number:confirm', quote_id: 'server-quote' });
    finish({ status: 'fulfilled', credential_id: 'credential', phone_number: quote.phone_number });
    await waitFor(() => expect(created).toHaveBeenCalledWith('credential', quote.phone_number));
});

it('takes the holder’s name, address and contact phone with the confirmation where the number’s country asks who holds it', async () => {
    const asks = {
        ...quote, country: 'NL', number_type: 'mobile' as const,
        requirements: {
            needs: 'address' as const,
            items: [asked('r-address', 'address', 'Worldwide Physical Address'), asked('r-contact', 'contact', 'Contact Information (Name, Business Name, Phone Number)')],
        },
    };
    const send = transport(() => ({ status: 'fulfilled', credential_id: 'credential', phone_number: asks.phone_number }));
    render(<MemoryRouter><PhoneNumberPurchaseForm sendEvent={send} onCredentialCreated={vi.fn()} confirmation={{ initialQuote: asks, onState: vi.fn() }} /></MemoryRouter>);
    const review = await screen.findByTestId('phone-purchase-confirmation');
    expect(review.textContent).toContain('Netherlands asks who holds a number before it’s sold. NoClick files these details with the carrier');
    // The quote shows before the account's phone arrives; the phone fills in when it does.
    await waitFor(() => expect((within(review).getByLabelText('Contact phone') as HTMLInputElement).value).toBe('+31 6 12345670'));
    const confirm = within(review).getByRole('button', { name: /Confirm purchase/ }) as HTMLButtonElement;
    expect(confirm.disabled).toBe(true);
    for (const [label, value] of [['Full name', 'Dana Ruiz'], ['Street address', 'Keizersgracht 1'], ['City', 'Amsterdam'], ['Postal code', '1015 CJ']]) {
        fireEvent.change(within(review).getByLabelText(label), { target: { value } });
    }
    fireEvent.click(confirm);
    await waitFor(() => expect(send.mock.calls.some((c) => c[0].event_name === 'phone_number:confirm')).toBe(true));
    expect(send.mock.calls.find((c) => c[0].event_name === 'phone_number:confirm')![0]).toEqual({
        event_name: 'phone_number:confirm', quote_id: 'server-quote',
        holder: {
            name: 'Dana Ruiz', business_name: null, street: 'Keizersgracht 1', street2: null, city: 'Amsterdam', region: null, postal_code: '1015 CJ', country: 'NL',
            phone: '+31612345670',
        },
    });
});

it('returns stale confirmations to selection without retrying a charge', async () => {
    const send = transport(() => ({ error: 'This confirmation has expired.' }));
    render(<MemoryRouter><PhoneNumberPurchaseForm sendEvent={send} onCredentialCreated={vi.fn()} confirmation={{ initialQuote: quote, onState: vi.fn() }} /></MemoryRouter>);
    fireEvent.click(await screen.findByRole('button', { name: /Confirm purchase/ }));
    expect(await screen.findByText('This confirmation has expired.')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Confirm purchase/ })).toBeNull();
    expect(send.mock.calls.filter((c) => c[0].event_name === 'phone_number:confirm')).toHaveLength(1);
});

it('hands uncertain outcomes to the status screen instead of inviting another purchase', async () => {
    const send = transport(() => Promise.reject(new Error('Network disconnected')));
    const onState = vi.fn();
    const created = vi.fn();
    render(<MemoryRouter><PhoneNumberPurchaseForm sendEvent={send} onCredentialCreated={created} confirmation={{ initialQuote: quote, onState }} /></MemoryRouter>);
    fireEvent.click(await screen.findByRole('button', { name: /Confirm purchase/ }));
    await waitFor(() => expect(onState).toHaveBeenCalledWith(expect.objectContaining({ status: 'provisioning' })));
    expect(created).not.toHaveBeenCalled();
    expect(send.mock.calls.filter((c) => c[0].event_name === 'phone_number:confirm')).toHaveLength(1);
});

// An Italian local number as Telnyx sells it: who holds it, which identity document, and the document.
const ITALY = {
    ...quote, phone_number: '+390212345678', country: 'IT',
    requirements: {
        needs: 'documents' as const,
        items: [
            asked('r-address', 'address', 'Worldwide Physical Address'),
            asked('r-type', 'textual', 'Identity Document Type', { values: ['Identity card', 'Passport'] }),
            asked('r-id', 'document', 'Identity Document'),
        ],
    },
};
const PASSPORT = { id: 'doc-1', requirement_id: 'r-id', requirement_name: 'Identity Document', filename: 'passport.pdf', uploaded_at: '2026-10-01T10:00:00Z' };
const ORDER = {
    id: 'order-1', phone_number: ITALY.phone_number, country: 'IT', number_type: 'local' as const, status: 'in_review' as const, reason: null,
    deadline: null, monthly_credits: 4, upfront_credits: 4, credential_id: null, created_at: '', requirements: ITALY.requirements,
};

it('takes the documents and answers on the confirmation, and hands an order in review to the page', async () => {
    const send = transport((event) => {
        if (event.event_name === 'phone_number:documents') return { documents: [PASSPORT] };
        return { status: 'in_review', order_id: 'order-1', order: ORDER };
    });
    const onState = vi.fn();
    render(<MemoryRouter><PhoneNumberPurchaseForm sendEvent={send} onCredentialCreated={vi.fn()} confirmation={{ initialQuote: ITALY, onState }} /></MemoryRouter>);
    const review = await screen.findByTestId('phone-purchase-confirmation');
    expect(review.textContent).toContain('Italy asks for documents before a number is sold.');
    expect(review.textContent).toContain('Due once approved');
    for (const [label, value] of [['Full name', 'Giulia Rossi'], ['Street address', 'Via Roma 1'], ['City', 'Milano'], ['Postal code', '20121']]) {
        fireEvent.change(within(review).getByLabelText(label), { target: { value } });
    }
    fireEvent.change(within(review).getByLabelText('Identity Document Type'), { target: { value: 'Passport' } });
    // The passport filed for an earlier number is offered again, and chosen.
    await waitFor(() => expect((within(review).getByRole('radio') as HTMLInputElement).checked).toBe(true));
    fireEvent.click(within(review).getByRole('button', { name: /Submit for review/ }));
    await waitFor(() => expect(onState).toHaveBeenCalledWith(expect.objectContaining({ status: 'in_review', order: ORDER })));
    expect(send.mock.calls.find((c) => c[0].event_name === 'phone_number:confirm')![0]).toMatchObject({
        quote_id: 'server-quote', holder: { name: 'Giulia Rossi', country: 'IT' }, answers: { 'r-type': 'Passport', 'r-id': 'doc-1' },
    });
});

it('says an order is in the carrier’s review, and resubmits one it sent back from the link', async () => {
    const send = vi.fn(async (event: Record<string, unknown>) => {
        if (event.event_name === 'phone_number:documents') return { documents: [PASSPORT] };
        return { status: 'in_review', order: { ...ORDER } };
    });
    const onState = vi.fn();
    const view = render(<MemoryRouter><OrderReview order={ORDER} sendEvent={send} onState={onState} /></MemoryRouter>);
    expect(screen.getByTestId('order-in-review').textContent).toContain('nothing is charged until it approves');
    // Nothing is searched to show an order.
    expect(send).not.toHaveBeenCalled();
    view.unmount();
    render(<MemoryRouter><OrderReview order={{ ...ORDER, status: 'rejected', reason: 'Upload the photo page.' }} sendEvent={send} onState={onState} /></MemoryRouter>);
    const step = await screen.findByTestId('requirements-step');
    expect(within(step).getByTestId('sent-back').textContent).toContain('Upload the photo page.');
    for (const [label, value] of [['Full name', 'Giulia Rossi'], ['Street address', 'Via Roma 1'], ['City', 'Milano'], ['Postal code', '20121']]) {
        fireEvent.change(within(step).getByLabelText(label), { target: { value } });
    }
    fireEvent.change(within(step).getByLabelText('Identity Document Type'), { target: { value: 'Identity card' } });
    await waitFor(() => expect((within(step).getByRole('radio') as HTMLInputElement).checked).toBe(true));
    fireEvent.click(within(step).getByRole('button', { name: 'Resubmit' }));
    await waitFor(() => expect(onState).toHaveBeenCalledWith(expect.objectContaining({ status: 'in_review' })));
    // The link resubmits its own order: no order id goes with it.
    const resubmitted = send.mock.calls.find((c) => c[0].event_name === 'phone_number:resubmit')![0];
    expect(resubmitted).not.toHaveProperty('order_id');
    expect(resubmitted).toMatchObject({ answers: { 'r-type': 'Identity card', 'r-id': 'doc-1' }, holder: { name: 'Giulia Rossi' } });
});
