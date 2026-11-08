import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';
import metadata from '~/schemas/nodeMeta/gong.json';

await loadNodeSchemas(['automation-gong']);

describe('Gong connection methods', () => {
    it('offers declared OAuth and access-key methods with matching scopes', () => {
        const methods = credentialRequirements('automation-gong').map(methodFromRequirement);
        expect(methods).toHaveLength(2);
        const oauth = methods.find(method => method.credential_type === 'gong_oauth')!;
        const key = methods.find(method => method.credential_type === 'gong_access_key')!;
        expect(oauth).toMatchObject({ method_kind: 'oauth', is_oauth: true, oauth_provider: 'gong' });
        expect(key).toMatchObject({ method_kind: 'api_key', is_oauth: false });
        expect(oauth.oauth_scopes).toContain('api:workspaces:read');
        expect(metadata.oauthProviders[0].scopes).toEqual(oauth.oauth_scopes);
        expect(metadata.oauthProviders[0].contextFields.api_base_url_for_customer.source).toBe('token');
        expect(getNodeCredentialInfo('automation-gong')?.acceptedTypes).toEqual(['gong_oauth', 'gong_access_key']);
    });
});
