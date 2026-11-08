import { beforeAll, describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { loadNodeSchemas } from '~/utils/nodeSchemas';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import metadata from '~/schemas/nodeMeta/webex.json';

beforeAll(() => loadNodeSchemas(['automation-webex']));

describe('Webex connection', () => {
    it('uses its declared OAuth provider and scopes', () => {
        const [requirement] = credentialRequirements('automation-webex');
        expect(requirement.label).toBe('Webex Account');
        expect(CREDENTIAL_TYPE_MAP.WebexOAuthCredential).toBe('webex_oauth');
        const method = methodFromRequirement(requirement);
        expect(method.method_kind).toBe('oauth');
        expect(method.oauth_provider).toBe('webex');
        expect(method.oauth_scopes).toContain('spark:people_read');
        expect(method.oauth_scopes).toContain('spark:kms');
        expect(metadata.oauthProviders[0].authorizeUrl).toBe('https://webexapis.com/v1/authorize');
    });
});
