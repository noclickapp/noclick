// Verifies that Wild Apricot offers its declared organization OAuth connection.
// This guards the metadata used to launch sign-in from workflow credentials.
import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { loadNodeSchemas } from '~/utils/nodeSchemas';
import { INTEGRATION_METADATA } from '~/utils/integrationMetadata';

await loadNodeSchemas(['automation-wild-apricot']);

describe('Wild Apricot connection', () => {
    it('uses the declared organization OAuth flow', () => {
        const methods = credentialRequirements('automation-wild-apricot').map(methodFromRequirement);
        expect(methods).toHaveLength(1);
        expect(methods[0]).toMatchObject({
            credential_type: 'wild_apricot_oauth', method_kind: 'oauth', is_oauth: true,
            oauth_provider: 'wild_apricot',
        });
        expect(INTEGRATION_METADATA.oauthProviders.wild_apricot).toMatchObject({
            authorizeUrl: 'https://{organization}/sys/login/OAuthLogin',
            scopes: ['auto'],
            contextFields: { organization: { source: 'input', kind: 'host' } },
        });
    });
});
