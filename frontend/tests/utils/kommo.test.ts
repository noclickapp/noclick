import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';
import { INTEGRATION_METADATA } from '~/utils/integrationMetadata';
import { getProviderConfigByCredentialType } from '~/utils/oauthProviders';

await loadNodeSchemas(['automation-kommo']);

describe('Kommo connection methods', () => {
    it('offers the tenant-aware OAuth sign-in and a manually issued token', () => {
        const methods = credentialRequirements('automation-kommo').map(methodFromRequirement);
        expect(methods).toHaveLength(2);
        expect(methods[0]).toMatchObject({ credential_type: 'kommo_oauth', method_kind: 'oauth', is_oauth: true, oauth_provider: 'kommo', oauth_scopes: [] });
        expect(methods[1]).toMatchObject({ credential_type: 'kommo_long_lived_token', method_kind: 'api_key', is_oauth: false });
        expect(getProviderConfigByCredentialType('kommo_oauth')?.oauthProvider).toBe('kommo');
        expect(getNodeCredentialInfo('automation-kommo')).toMatchObject({ providerKey: 'kommo', label: 'Kommo Account', acceptedTypes: ['kommo_oauth', 'kommo_long_lived_token'] });
        expect(INTEGRATION_METADATA.oauthProviders.kommo).toMatchObject({
            authorizeUrl: 'https://www.kommo.com/oauth',
            authorizeParams: { mode: 'post_message' },
            contextFields: { referer: { source: 'callback', kind: 'host', pattern: '[a-z0-9-]+\\.kommo\\.com' } },
        });
    });
});
