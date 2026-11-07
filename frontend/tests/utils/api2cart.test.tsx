// @vitest-environment happy-dom
// API2Cart schema and manual credential forms with synthetic keys and responses.
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';

import schema from '~/schemas/nodes/api2cart.json';
import { getNodeCredentialInfo, NODE_SCHEMAS, loadNodeSchemas } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { CredentialCreatePanel } from '~/components/credential/CredentialCreatePanel';
import { CredentialMethodConnect } from '~/components/credential/CredentialMethodConnect';
const SECRET = 'synthetic-api2cart-form-key';
const PLATFORM = 'Shopify';
const STORE = '1';
const STORE_KEY = 'synthetic-api2cart-form-store-key';
const credentialSchema = schema.$defs.API2CartAPIKeyCredential;
const fields = Object.entries(credentialSchema.properties)
    .filter(([name]) => name !== 'credential_type')
    .map(([name, definition]) => ({ name, label: definition.title ?? name,
        required: credentialSchema.required.includes(name as never),
        type: (definition as { 'ui:widget'?: string })['ui:widget'] === 'password' ? 'password' : 'text' }));
let logs: ReturnType<typeof vi.spyOn>[] = [];

beforeAll(() => loadNodeSchemas(['automation-api2cart']));
beforeEach(() => {
    logs = ['log', 'warn', 'error', 'debug'].map(method => vi.spyOn(console, method as 'log').mockImplementation(() => undefined));
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

function fill() {
    for (const [field, value] of Object.entries({ api_key: SECRET, store_key: STORE_KEY, platform_id: PLATFORM, store_id: STORE })) {
        fireEvent.change(document.querySelector(`[data-field="${field}"] input`)!, { target: { value } });
    }
}

describe('API2Cart native credential and parent choices', () => {
    it('uses one manual API-key family in both selectors and fixed-store native choices', () => {
        expect(getNodeCredentialInfo('automation-api2cart')?.acceptedTypes).toEqual(['api2cart_api_key']);
        expect(getCredentialTypeFromSchemaTitle('API2CartAPIKeyCredential')).toBe('api2cart_api_key');
        expect(NODE_SCHEMAS['automation-api2cart']).toBe(schema);
        expect(credentialSchema).not.toHaveProperty('x-oauth-provider');
        expect(fields.map(field => [field.name, field.type])).toEqual([['api_key', 'password'], ['store_key', 'password'], ['platform_id', 'text'], ['store_id', 'text']]);
        for (const name of ['API2CartGetProductConfig', 'API2CartGetCategoryConfig', 'API2CartGetCustomerConfig', 'API2CartGetOrderConfig']) {
            expect(schema.$defs[name as keyof typeof schema.$defs]).toBeDefined();
        }
        expect(schema.$defs.API2CartGetProductConfig.properties.product_id).toMatchObject({
            'x-dynamic-options': { field_name: 'product_id', allow_custom: true },
        });
        expect(Object.keys(schema.$defs).filter(name => name.endsWith('Config') && name !== 'API2CartNodeConfig')).toHaveLength(18);
    });

    it.each([true, false])('saves the API2Cart fields and shows a refused save: %s', async success => {
        const save = vi.fn(async (_name: string, _data: Record<string, string>) => success ? null : {
            error: 'Access key rejected', fieldErrors: { api_key: 'Access key rejected' },
        });
        render(<CredentialCreatePanel app="API2Cart" fields={fields} onSave={save} />);
        fill();
        expect(document.querySelector('[data-field="api_key"] input')!.getAttribute('type')).toBe('password');
        expect(document.querySelector('[data-field="store_key"] input')!.getAttribute('type')).toBe('password');
        fireEvent.click(screen.getByRole('button', { name: 'Connect' }));
        await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
        expect(save.mock.calls[0][1]).toEqual({ api_key: SECRET, store_key: STORE_KEY, platform_id: PLATFORM, store_id: STORE });
        await waitFor(() => expect(screen.getByRole('button', { name: 'Connect' }).hasAttribute('disabled')).toBe(false));
        expect(screen.queryAllByText('Access key rejected').length > 0).toBe(!success);
    });

    it.each([200, 422, 'network'])('actual anonymous method uses the exact native fields and preserves %s outcome', async status => {
        const provided = vi.fn();
        const fetch = vi.fn(async (_url: string, _init: RequestInit) => {
            if (status === 'network') throw new Error(SECRET);
            return new Response(JSON.stringify(status === 200 ? { verification: { reachable: true, account_label: null } } : {
                detail: { message: 'Access key rejected', field_errors: { api_key: 'Access key rejected' } } }),
                { status: status as number, headers: { 'Content-Type': 'application/json' } });
        });
        vi.stubGlobal('fetch', fetch);
        render(<MemoryRouter><CredentialMethodConnect method={{ credential_type: 'api2cart_api_key', label: 'API2Cart API Key',
            is_oauth: false, method_kind: 'api_key', credential_fields: fields }} apiBase="https://api.example.test"
            token="synthetic-provide-capability" serviceName="API2Cart" onProvided={provided} /></MemoryRouter>);
        expect(screen.queryByPlaceholderText('My API2Cart API Key')).toBeNull();
        fill();
        fireEvent.click(screen.getByText('Connect'));
        await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
        const [url, init] = fetch.mock.calls[0];
        expect(url).toBe('https://api.example.test/api/credential-request/synthetic-provide-capability/provide');
        expect(JSON.parse(init.body as string)).toEqual({ credential_type: 'api2cart_api_key',
            credential_data: { api_key: SECRET, store_key: STORE_KEY, platform_id: PLATFORM, store_id: STORE } });
        if (status === 200) await waitFor(() => expect(provided).toHaveBeenCalledWith({ reachable: true, account_label: null }));
        else await waitFor(() => expect(screen.getAllByText(status === 422 ? 'Access key rejected' : 'Failed to submit credential. Please try again.')[0]).toBeTruthy());
        expect(JSON.stringify(logs.flatMap(log => log.mock.calls))).not.toContain(SECRET);
        expect(JSON.stringify(logs.flatMap(log => log.mock.calls))).not.toContain(STORE_KEY);
    });

});
