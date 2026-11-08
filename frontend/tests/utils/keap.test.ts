import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';
import { INTEGRATION_METADATA } from '~/utils/integrationMetadata';

await loadNodeSchemas(['automation-keap']);

describe('Keap credential methods', () => {
    it('discovers OAuth and personal-token connections independently', () => {
        const methods = credentialRequirements('automation-keap').map(methodFromRequirement);
        expect(methods).toHaveLength(2);
        expect(methods.find(method => method.credential_type === 'keap_oauth')).toMatchObject({
            method_kind: 'oauth', is_oauth: true, oauth_provider: 'keap', oauth_scopes: ['full'],
        });
        expect(methods.find(method => method.credential_type === 'keap_pat')).toMatchObject({
            method_kind: 'api_key', is_oauth: false,
        });
        expect(getNodeCredentialInfo('automation-keap')?.label).toBe('Keap Account');
        expect(INTEGRATION_METADATA.oauthProviders.keap).toMatchObject({
            authorizeUrl: 'https://accounts.infusionsoft.com/app/oauth/authorize',
            credentialType: 'keap_oauth', scopes: ['full'],
        });
    });
});
