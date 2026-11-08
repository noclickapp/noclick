import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';
import { INTEGRATION_METADATA } from '~/utils/integrationMetadata';
import { getProviderConfigByCredentialType } from '~/utils/oauthProviders';

await loadNodeSchemas(['automation-mural']);

describe('Mural self-registering OAuth connection', () => {
    it('resolves the account method and generic sign-in from generated metadata', () => {
        expect(getNodeCredentialInfo('automation-mural')).toEqual({
            providerKey: 'mural', acceptedTypes: ['mural_oauth'], label: 'Mural Account',
        });
        const methods = credentialRequirements('automation-mural').map(methodFromRequirement);
        expect(methods).toHaveLength(1);
        expect(methods[0]).toMatchObject({
            credential_type: 'mural_oauth', method_kind: 'oauth', is_oauth: true,
            oauth_provider: 'mural',
        });
        expect(getProviderConfigByCredentialType('mural_oauth')?.oauthProvider).toBe('mural');
        const provider = INTEGRATION_METADATA.oauthProviders.mural;
        expect(provider).toMatchObject({
            provider: 'mural', pkce: true, credentialType: 'mural_oauth',
            authorizeUrl: 'https://app.mural.co/api/public/v1/authorization/oauth2/',
        });
        expect(methods[0].oauth_scopes).toEqual(provider.scopes);
    });
});
