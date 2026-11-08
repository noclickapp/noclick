// The connect link's OAuth transport hands the server the exchange event as the app's connect form built it: the
// code, and the form's own inputs (a site, a subdomain, a shop), because the link runs the app's own sign-in.

import { afterEach, describe, expect, it, vi } from 'vitest';
import { provideLinkTransport } from '~/components/credential/provideLinkTransport';

describe('provideLinkTransport redirect OAuth', () => {
    afterEach(() => vi.unstubAllGlobals());

    it('sends the code and every input the connect form put beside it', async () => {
        const fetch = vi.fn(async () => new Response(JSON.stringify({ status: 'success', credential_id: 'cred-1' })));
        vi.stubGlobal('fetch', fetch);
        const exchange = provideLinkTransport('https://api.test', 'tok', 'zendesk_oauth');

        const answer = await exchange({
            event_name: 'zendesk:oauth:exchange',
            code: 'code-1',
            redirect_uri: 'https://noclick.test/oauth/zendesk/callback',
            scopes: ['read'],
            subdomain: 'acme',
            credential_name: 'Zendesk',
        });

        expect(answer).toEqual({ success: true, credential_id: 'cred-1', message: undefined });
        const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
        expect(url).toBe('https://api.test/api/credential-request/tok/provide');
        expect(JSON.parse(init.body as string)).toEqual({
            credential_type: 'zendesk_oauth',
            oauth_code: 'code-1',
            redirect_uri: 'https://noclick.test/oauth/zendesk/callback',
            scopes: ['read'],
            oauth_inputs: { subdomain: 'acme', credential_name: 'Zendesk' },
        });
    });
});

it('maps declared device start and poll to link-bound endpoints without exposing a device code', async () => {
    const fetch = vi.fn(async (_url: string, _init?: RequestInit) => new Response(JSON.stringify({ success: true, status: 'pending', authorization_id: 'opaque' })));
    vi.stubGlobal('fetch', fetch);
    try {
        const transport = provideLinkTransport('https://api.test', 'request', 'example_oauth');
        await transport({ event_name: 'oauth:device:start', provider: 'example', scopes: ['read'], context: { region: 'eu' } });
        expect(fetch.mock.calls[0][0]).toBe('https://api.test/api/credential-request/request/oauth-device/start');
        expect(JSON.parse((fetch.mock.calls[0] as any)[1].body)).toEqual({ credential_type: 'example_oauth', scopes: ['read'], context: { region: 'eu' } });
        await transport({ event_name: 'oauth:device:poll', provider: 'example', authorization_id: 'opaque' });
        expect(fetch.mock.calls[1][0]).toBe('https://api.test/api/credential-request/request/oauth-device/poll');
        expect(JSON.parse((fetch.mock.calls[1] as any)[1].body)).toEqual({ credential_type: 'example_oauth', authorization_id: 'opaque' });
    } finally { vi.unstubAllGlobals(); }
});
