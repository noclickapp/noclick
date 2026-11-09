/** Verifies Estimate Rocket uses its self-declared OAuth provider and published scopes.
 * Keeps credential method discovery and its industry catalog placement covered. */
import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { loadNodeSchemas } from '~/utils/nodeSchemas';
import metadata from '~/schemas/nodeMeta/converted-da-56088.json';
import { EstimateRocketNode } from '~/components/workflow/nodes/integrations/converted-da-56088';

await loadNodeSchemas(['automation-converted-da-56088']);

describe('Estimate Rocket OAuth connection', () => {
    it('connects with the declared provider and the published read/write scopes', () => {
        const methods = credentialRequirements('automation-converted-da-56088').map(methodFromRequirement);
        expect(methods).toHaveLength(1);
        expect(methods[0]).toMatchObject({
            credential_type: 'estimaterocket_oauth', method_kind: 'oauth', is_oauth: true,
            oauth_provider: 'estimaterocket', oauth_scopes: ['read', 'write'],
        });
        expect(metadata.oauthProviders[0]).toMatchObject({
            provider: 'estimaterocket', credentialType: 'estimaterocket_oauth',
            authorizeUrl: 'https://estimate-rocket-api.herokuapp.com/oauth/authorize',
            clientIdEnv: 'ESTIMATE_ROCKET_CLIENT_ID', clientSecretEnv: 'ESTIMATE_ROCKET_CLIENT_SECRET',
            redirectUriEnv: 'ESTIMATE_ROCKET_REDIRECT_URI',
        });
        expect(EstimateRocketNode.label).toBe('Estimate Rocket');
        expect(EstimateRocketNode.category).toBe('industry');
    });
});
