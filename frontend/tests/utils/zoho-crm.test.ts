import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { loadNodeSchemas } from '~/utils/nodeSchemas';
import { INTEGRATION_METADATA } from '~/utils/integrationMetadata';

await loadNodeSchemas(['automation-zoho-crm']);

describe('Zoho CRM connection', () => {
    it('uses the declared regional OAuth flow', () => {
        const methods = credentialRequirements('automation-zoho-crm').map(methodFromRequirement);
        expect(methods).toHaveLength(1);
        expect(methods[0]).toMatchObject({
            credential_type: 'zoho_crm_oauth', method_kind: 'oauth', is_oauth: true,
            oauth_provider: 'zoho_crm',
        });
        expect(INTEGRATION_METADATA.oauthProviders.zoho_crm).toMatchObject({
            scopeSeparator: ',',
            authorizeUrl: 'https://accounts.zoho.com/oauth/v2/auth',
            contextFields: {
                accounts_server: { source: 'callback', callbackName: 'accounts-server', kind: 'origin' },
                api_domain: { source: 'token', kind: 'origin' },
            },
        });
    });
});
