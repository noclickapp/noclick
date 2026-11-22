// A step's settings as a copy and a saved file carry them: every secret left out, by the rule the platform reads a
// workflow by, and nothing else touched.
import { describe, expect, it } from 'vitest';
import { withoutSecrets } from './stepSecrets';

describe('a step’s settings without their secrets', () => {
    it('leaves out a setting its name marks, never an address or a yes or no', () => {
        expect(
            withoutSecrets({
                label: 'Fetch orders',
                operation: 'get',
                api_key: 'sk-live',
                apikey: 'sk-live',
                client_secret: 's3cret',
                access_token: 'tok',
                password: 'hunter2',
                pat: 'ghp_x',
                token_url: 'https://auth.example.test/token',
                secret: true,
                keyword: 'orders',
            })
        ).toEqual({ label: 'Fetch orders', operation: 'get', token_url: 'https://auth.example.test/token', secret: true, keyword: 'orders' });
    });

    it('keeps the accounts a step holds: they’re references', () => {
        expect(withoutSecrets({ credentialIds: { slack_oauth: 'cred_slack', api_key: 'cred_key' }, token: 'tok' })).toEqual({
            credentialIds: { slack_oauth: 'cred_slack', api_key: 'cred_key' },
        });
    });

    it('leaves out the value of a row named as a secret, and keeps the row', () => {
        const settings = {
            headers: [
                { key: 'Authorization', value: 'Bearer abc', enabled: true },
                { key: 'Accept', value: 'application/json', enabled: true },
                { name: 'X-Api-Key', value: 'k' },
                { key: 'Cookie', value: 'session=1' },
                { key: 'X-Token-Enabled', value: true },
            ],
            query_params: [{ key: 'access_token', value: 't' }, { key: 'page', value: '2' }],
        };
        expect(withoutSecrets(settings)).toEqual({
            headers: [
                { key: 'Authorization', enabled: true },
                { key: 'Accept', value: 'application/json', enabled: true },
                { name: 'X-Api-Key' },
                { key: 'Cookie' },
                { key: 'X-Token-Enabled', value: true },
            ],
            query_params: [{ key: 'access_token' }, { key: 'page', value: '2' }],
        });
        // What it was handed is left as it was.
        expect(settings.headers[0]).toEqual({ key: 'Authorization', value: 'Bearer abc', enabled: true });
    });

    it('leaves out a secret at any depth, and an entry of a map of headers by its name', () => {
        expect(
            withoutSecrets({
                auth: { username: 'ada', password: 'hunter2', oauth: { client_id: 'id', client_secret: 's' } },
                request_headers: { Authorization: 'Bearer abc', 'Proxy-Authorization': 'Basic x', Accept: 'text/plain' },
                items: [{ id: 1, token: 't', note: 'kept' }],
            })
        ).toEqual({
            auth: { username: 'ada', oauth: { client_id: 'id' } },
            request_headers: { Accept: 'text/plain' },
            items: [{ id: 1, note: 'kept' }],
        });
    });

    it('leaves out a setting its type’s schema marks, for the step’s operation', () => {
        const schema = {
            properties: { config: { $ref: '#/$defs/Config' } },
            $defs: {
                Config: { oneOf: [{ $ref: '#/$defs/Send' }, { $ref: '#/$defs/Read' }] },
                Send: {
                    properties: {
                        operation: { const: 'send' },
                        passphrase: { type: 'string', 'ui:widget': 'password' },
                        signature: { type: 'string', writeOnly: true },
                        pin: { type: 'string', format: 'password' },
                        to: { type: 'string' },
                    },
                },
                Read: { properties: { operation: { const: 'read' }, passphrase: { type: 'string' } } },
            },
        };
        const settings = { passphrase: 'open sesame', signature: 'sig', pin: '1234', to: 'ada@example.test' };
        expect(withoutSecrets({ operation: 'send', ...settings }, schema)).toEqual({ operation: 'send', to: 'ada@example.test' });
        // Another operation declares the same name as plain text.
        expect(withoutSecrets({ operation: 'read', ...settings }, schema)).toEqual({ operation: 'read', ...settings });
        // No operation chosen yet: every operation's marks count.
        expect(withoutSecrets(settings, schema)).toEqual({ to: 'ada@example.test' });
        // A schema with no operations.
        expect(withoutSecrets({ code: 'c', note: 'n' }, { properties: { code: { writeOnly: true }, note: {} } })).toEqual({ note: 'n' });
    });
});
