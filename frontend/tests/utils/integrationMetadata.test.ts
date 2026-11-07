// Exercise the leaf metadata merge without loading a node schema or component.
// Conflicting declarations must fail independently of import order.
import { describe, expect, it } from 'vitest';
import { collectIntegrationMetadata, INTEGRATION_METADATA, mergeDeclarations } from '~/utils/integrationMetadata';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { NODE_SCHEMA_TYPES, isAgentToolProviderType } from '~/utils/nodeMeta';

const example = {
    type: 'automation-example', nodeMeta: { agentToolProvider: true },
    credentialTypes: { ExampleCredential: 'example_api_key' },
    providerLabels: { example: 'Example API Key' }, autoSelectCredential: true,
};

describe('integration metadata', () => {
    it('collects per-type facts and extends existing entries', () => {
        const result = collectIntegrationMetadata({ '../schemas/nodeMeta/example.json': example });
        expect(result.nodeMeta).toEqual({ 'automation-example': { agentToolProvider: true } });
        expect(result.autoSelectTypes).toEqual(['automation-example']);
        expect(mergeDeclarations({ Existing: 'existing' }, result.credentialTypes)).toEqual({ Existing: 'existing', ExampleCredential: 'example_api_key' });
    });
    it('rejects conflicting credential titles and path/type mismatches', () => {
        expect(() => mergeDeclarations({ Example: 'a' }, { Example: 'b' })).toThrow(/Conflicting/);
        expect(() => collectIntegrationMetadata({ 'wrong.json': example })).toThrow(/Invalid/);
        expect(mergeDeclarations({ Example: 'a' }, { Example: 'a' })).toEqual({ Example: 'a' });
    });
    it('merges every generated integration into the public readers', () => {
        for (const [type, meta] of Object.entries(INTEGRATION_METADATA.nodeMeta)) {
            expect(NODE_SCHEMA_TYPES).toContain(type);
            expect(isAgentToolProviderType(type)).toBe(meta.agentToolProvider === true);
        }
        for (const [title, type] of Object.entries(INTEGRATION_METADATA.credentialTypes)) {
            expect(CREDENTIAL_TYPE_MAP[title]).toBe(type);
        }
        expect(CREDENTIAL_TYPE_MAP.GoogleSheetsOAuthCredential).toBe('google_sheets_oauth');
    });
});


it('rejects duplicate OAuth ids and credentials absent from an integration schema', () => {
    const oauth = { provider: 'example', authorizeUrl: 'https://example.com/authorize', scopes: ['read'], pkce: false, clientIdEnv: 'EXAMPLE_CLIENT_ID', redirectUriEnv: 'EXAMPLE_REDIRECT_URI', authorizeParams: {}, credentialType: 'example_api_key' };
    const first = { ...example, oauthProviders: [oauth] };
    const second = { ...first, type: 'automation-second' };
    expect(() => collectIntegrationMetadata({ 'example.json': first, 'second.json': second })).toThrow(/Duplicate OAuth/);
    expect(() => collectIntegrationMetadata({ 'example.json': { ...first, oauthProviders: [{ ...oauth, credentialType: 'missing' }] } })).toThrow(/Unknown OAuth credential/);
});
