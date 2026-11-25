// @vitest-environment happy-dom
// Buy a number whose country asks for documents, over the SDK (the console's and the open app's Resources transport):
// the document goes to the carrier through PhoneNumber.uploadDocument, the purchase carries the typed answers and the
// document's id, and a number the carrier reviews first comes back as its order. The documents and orders the account
// keeps are read through the API, and a kept document can be removed.
import { act, renderHook, waitFor } from '@testing-library/react';
import { DEFAULT_BASE_URL, NoClick } from 'noclick';
import type { ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { ConsoleScope } from '../../ConsoleProviders';
import { fixtureConsole } from '../../fixtures/context';
import { usePhoneNumberPurchase, type AvailableNumber } from '@/screens/numbers/usePhoneNumberPurchase';
import { useConsoleNumberTransport } from './PhoneNumbersPanel';

const NUMBER: AvailableNumber = {
    phone_number: '+31201234567', country: 'NL', number_type: 'local', locality: 'Amsterdam', region: '', capabilities: ['voice'],
    monthly_usd: 2, upfront_usd: 1, texting: false,
    requirements: { needs: 'documents', items: [
        { id: 'req_id', name: 'Proof of address', kind: 'document', description: '' },
        { id: 'req_vat', name: 'VAT number', kind: 'textual', description: '' },
    ] },
} as unknown as AvailableNumber;

describe('buying a number that needs documents, over the SDK', () => {
    it('uploads the document, buys with the typed answers, and lands as an order', async () => {
        const calls: { method: string; path: string; body: unknown }[] = [];
        const fetch = vi.fn(async (input: string | URL | Request, init: RequestInit = {}) => {
            const url = new URL(String(input));
            const body = typeof init.body === 'string' ? JSON.parse(init.body) : null;
            calls.push({ method: init.method ?? 'GET', path: url.pathname, body });
            const json = (value: unknown) => new Response(JSON.stringify(value), { headers: { 'content-type': 'application/json' } });
            if (url.pathname === '/v1/phone_numbers/coverage') return json({ data: [] });
            if (url.pathname === '/v1/phone_numbers/documents' && (init.method ?? 'GET') === 'GET') return json({ object: 'list', data: [] });
            if (url.pathname === '/v1/phone_numbers/orders') return json({ object: 'list', data: [] });
            if (url.pathname === '/v1/phone_numbers/documents') {
                return json({ object: 'phone_number_document', id: 'doc_1', requirement_id: 'req_id', requirement_name: 'Proof of address',
                    filename: 'lease.pdf', uploaded_at: '2026-11-25T10:00:00Z' });
            }
            if (url.pathname === '/v1/phone_numbers') return json({ object: 'phone_number_order', id: 'ord_1', number: '+31201234567', status: 'in_review' });
            return new Response('{}', { status: 404 });
        });
        const client = new NoClick({ apiKey: 'k', baseUrl: DEFAULT_BASE_URL, maxRetries: 0, fetch });
        const ordered = vi.fn();
        const wrapper = ({ children }: { children: ReactNode }) => <ConsoleScope value={fixtureConsole({ client, actsAs: 'owner' })}>{children}</ConsoleScope>;
        const { result } = renderHook(() => usePhoneNumberPurchase({
            transport: useConsoleNumberTransport(client, { user: null, name: '' }), country: 'NL', onOrdered: ordered, onCredentialCreated: () => {},
        }), { wrapper });

        await act(async () => result.current.loadDocuments());
        expect(result.current.documents).toEqual([]); // the account keeps none yet
        expect(result.current.removeDocument).toBeTypeOf('function');
        expect(calls.some((c) => c.method === 'GET' && c.path === '/v1/phone_numbers/documents')).toBe(true);

        const file = new File(['%PDF'], 'lease.pdf', { type: 'application/pdf' });
        let uploaded: Awaited<ReturnType<typeof result.current.uploadDocument>> = null;
        await act(async () => {
            uploaded = await result.current.uploadDocument(NUMBER, NUMBER.requirements!.items[0]!, file);
        });
        expect(uploaded).toMatchObject({ id: 'doc_1', requirement_id: 'req_id', filename: 'lease.pdf' });
        expect(calls.find((c) => c.method === 'POST' && c.path === '/v1/phone_numbers/documents')?.body).toMatchObject({ country: 'NL', requirement_id: 'req_id', filename: 'lease.pdf' });

        await act(async () => {
            await result.current.buy(NUMBER, { answers: { req_id: 'doc_1', req_vat: 'NL123' } });
        });
        expect(calls.find((c) => c.method === 'POST' && c.path === '/v1/phone_numbers')?.body).toMatchObject({
            requirements: { req_id: 'doc_1', req_vat: 'NL123' },
        });
        await waitFor(() => expect(ordered).toHaveBeenCalledWith({ order_id: 'ord_1', phone_number: '+31201234567' }));
        expect(calls.some((c) => c.path === '/v1/phone_numbers/orders')).toBe(true);
    });
});
