import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';
import { INTEGRATION_METADATA } from '~/utils/integrationMetadata';
import { getProviderConfigByCredentialType } from '~/utils/oauthProviders';

await loadNodeSchemas(['automation-mycase']);

describe('MyCase connection method', () => {
    it('discovers the declared OAuth sign-in and account label', () => {
        const methods = credentialRequirements('automation-mycase').map(methodFromRequirement);
        expect(methods).toHaveLength(1);
        expect(methods[0]).toMatchObject({ credential_type: 'mycase_oauth', method_kind: 'oauth', is_oauth: true, oauth_provider: 'mycase', oauth_scopes: [] });
        expect(getProviderConfigByCredentialType('mycase_oauth')?.oauthProvider).toBe('mycase');
        expect(getNodeCredentialInfo('automation-mycase')).toMatchObject({ providerKey: 'mycase', label: 'MyCase Account', acceptedTypes: ['mycase_oauth'] });
        expect(INTEGRATION_METADATA.oauthProviders.mycase).toMatchObject({
            authorizeUrl: 'https://auth.mycase.com/login_sessions/new',
            clientIdEnv: 'MYCASE_CLIENT_ID',
            redirectUriEnv: 'MYCASE_REDIRECT_URI',
        });
    });
});
