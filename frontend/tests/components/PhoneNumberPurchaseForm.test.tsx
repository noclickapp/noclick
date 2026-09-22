// @vitest-environment jsdom
// Exercise the shared phone form's owner-confirmation mode. Selecting a number
// must only prepare a quote; a separate explicit click authorizes its purchase.
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, expect, it, vi } from 'vitest';

vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/utils/credentialAutoSelect', () => ({ invalidateCredentialsCache: vi.fn() }));
vi.mock('~/components/utils/UpgradePopup', () => ({ UpgradePopup: () => null }));
import { PhoneNumberPurchaseForm } from '~/components/credential/PhoneNumberPurchaseForm';

const quote = { id: 'server-quote', phone_number: '+15674833618', monthly_credits: 15, expires_at: '2099-01-01T00:00:00Z' };
afterEach(cleanup);

it('reviews the selected number and recurring cost before confirming only the quote id', async () => {
    let finish: (value: unknown) => void = () => {};
    const send = vi.fn(async (event) => {
        if (event.event_name === 'phone_number:search') return { numbers: [{ ...quote, locality: 'Lucas', region: 'OH', capabilities: ['voice'] }], monthly_credits: 15 };
        if (event.event_name === 'phone_number:quote') return { quote };
        return new Promise(resolve => { finish = resolve; });
    });
    const created = vi.fn();
    render(<MemoryRouter><PhoneNumberPurchaseForm sendEvent={send} onCredentialCreated={created} confirmation={{ onState: vi.fn() }} /></MemoryRouter>);
    expect(send).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Find numbers' }));
    fireEvent.click(await screen.findByRole('button', { name: /Review ·/ }));
    const confirm = await screen.findByRole('button', { name: /Confirm purchase/ });
    expect(screen.getByText('Renews monthly')).toBeTruthy();
    expect(screen.getByText(/Call usage is billed separately/)).toBeTruthy();
    expect(send.mock.calls.map(c => c[0].event_name)).toEqual(['phone_number:search', 'phone_number:quote']);
    fireEvent.click(confirm); fireEvent.click(confirm);
    expect(send.mock.calls.filter(c => c[0].event_name === 'phone_number:confirm')).toHaveLength(1);
    expect(send).toHaveBeenLastCalledWith({ event_name: 'phone_number:confirm', quote_id: 'server-quote' });
    finish({ status: 'fulfilled', credential_id: 'credential', phone_number: quote.phone_number });
    await waitFor(() => expect(created).toHaveBeenCalledWith('credential', quote.phone_number));
});

it('returns stale confirmations to selection without retrying a charge', async () => {
    const send = vi.fn().mockResolvedValue({ error: 'This confirmation has expired.' });
    render(<MemoryRouter><PhoneNumberPurchaseForm sendEvent={send} onCredentialCreated={vi.fn()} confirmation={{ initialQuote: quote, onState: vi.fn() }} /></MemoryRouter>);
    fireEvent.click(screen.getByRole('button', { name: /Confirm purchase/ }));
    expect(await screen.findByText('This confirmation has expired.')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Confirm purchase/ })).toBeNull();
    expect(send).toHaveBeenCalledTimes(1);
});

it('hands uncertain outcomes to the status screen instead of inviting another purchase', async () => {
    const send = vi.fn().mockRejectedValue(new Error('Network disconnected'));
    const onState = vi.fn();
    const created = vi.fn();
    render(<MemoryRouter><PhoneNumberPurchaseForm sendEvent={send} onCredentialCreated={created} confirmation={{ initialQuote: quote, onState }} /></MemoryRouter>);
    fireEvent.click(screen.getByRole('button', { name: /Confirm purchase/ }));
    await waitFor(() => expect(onState).toHaveBeenCalledWith(expect.objectContaining({ status: 'provisioning' })));
    expect(created).not.toHaveBeenCalled();
    expect(send).toHaveBeenCalledTimes(1);
});
