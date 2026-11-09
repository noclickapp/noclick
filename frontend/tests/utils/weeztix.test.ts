import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { loadNodeSchemas } from '~/utils/nodeSchemas';
import { INTEGRATION_METADATA } from '~/utils/integrationMetadata';
import { WeeztixNode } from '~/components/workflow/nodes/integrations/weeztix';

await loadNodeSchemas(['automation-weeztix']);

describe('Weeztix connection', () => {
    it('uses its declared OAuth flow and bookings category', () => {
        expect(WeeztixNode.category).toBe('bookings');
        const methods = credentialRequirements('automation-weeztix').map(methodFromRequirement);
        expect(methods).toHaveLength(1);
        expect(methods[0]).toMatchObject({
            credential_type: 'weeztix_oauth', method_kind: 'oauth', is_oauth: true,
            oauth_provider: 'weeztix',
        });
        expect(INTEGRATION_METADATA.oauthProviders.weeztix).toMatchObject({
            authorizeUrl: 'https://login.weeztix.com/login', pkce: false,
        });
    });
});
