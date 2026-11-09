import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';
import { INTEGRATION_METADATA } from '~/utils/integrationMetadata';
import { getProviderConfigByCredentialType } from '~/utils/oauthProviders';

await loadNodeSchemas(['automation-net2phone']);

describe('net2phone connection methods', () => {
    it('offers both a pasted access token and the declared OAuth sign-in', () => {
        expect(getNodeCredentialInfo('automation-net2phone')).toMatchObject({
            providerKey: 'net2phone', label: 'net2phone Account',
        });
        const methods = credentialRequirements('automation-net2phone').map(methodFromRequirement);
        expect(methods).toHaveLength(2);
        expect(methods.find(method => method.credential_type === 'net2phone_access_token')).toMatchObject({
            method_kind: 'api_key', is_oauth: false,
        });
        expect(methods.find(method => method.credential_type === 'net2phone_oauth')).toMatchObject({
            method_kind: 'oauth', is_oauth: true, oauth_provider: 'net2phone',
        });
        expect(getProviderConfigByCredentialType('net2phone_oauth')?.oauthProvider).toBe('net2phone');
        expect(INTEGRATION_METADATA.oauthProviders.net2phone).toMatchObject({
            provider: 'net2phone', credentialType: 'net2phone_oauth', pkce: false,
            authorizeUrl: 'https://api.n2p.io/v1/oauth/authorize/n2p/',
            scopes: [],
        });
    });
});
