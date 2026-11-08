import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { loadNodeSchemas } from '~/utils/nodeSchemas';
import metadata from '~/schemas/nodeMeta/tidy.json';

await loadNodeSchemas(['automation-tidy']);

describe('Tidy OAuth connection', () => {
    it('uses its declared provider with role-based access and no named scopes', () => {
        const methods = credentialRequirements('automation-tidy').map(methodFromRequirement);
        expect(methods).toHaveLength(1);
        expect(methods[0]).toMatchObject({
            credential_type: 'tidy_oauth', method_kind: 'oauth', is_oauth: true,
            oauth_provider: 'tidy', oauth_scopes: [],
        });
        expect(metadata.oauthProviders[0]).toMatchObject({
            provider: 'tidy', credentialType: 'tidy_oauth',
            authorizeUrl: 'https://accounts.tidyhq.com/oauth/authorize',
            clientIdEnv: 'TIDY_CLIENT_ID', clientSecretEnv: 'TIDY_CLIENT_SECRET',
            redirectUriEnv: 'TIDY_REDIRECT_URI',
        });
    });
});
