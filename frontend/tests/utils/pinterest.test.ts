import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';
import metadata from '~/schemas/nodeMeta/pinterest.json';

await loadNodeSchemas(['automation-pinterest']);

describe('Pinterest connection methods', () => {
    it('offers the declared OAuth sign-in and a separate manually issued token', () => {
        const methods = credentialRequirements('automation-pinterest').map(methodFromRequirement);
        expect(methods).toHaveLength(2);
        const oauth = methods.find(method => method.credential_type === 'pinterest_oauth')!;
        const token = methods.find(method => method.credential_type === 'pinterest_access_token')!;
        expect(oauth).toMatchObject({ method_kind: 'oauth', is_oauth: true, oauth_provider: 'pinterest' });
        expect(token).toMatchObject({ method_kind: 'api_key', is_oauth: false });
        expect(oauth.oauth_scopes).not.toContain('msot:write');
        expect(oauth.oauth_scopes).toContain('user_accounts:read');
        expect(metadata.oauthProviders[0].scopes).toEqual(oauth.oauth_scopes);
        expect(metadata.oauthProviders[0].credentialType).toBe(oauth.credential_type);
        expect(getNodeCredentialInfo('automation-pinterest')?.acceptedTypes).toEqual(['pinterest_oauth', 'pinterest_access_token']);
    });
});
