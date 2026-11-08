import { beforeAll, describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { loadNodeSchemas } from '~/utils/nodeSchemas';
import metadata from '~/schemas/nodeMeta/todoist.json';

beforeAll(() => loadNodeSchemas(['automation-todoist']));

describe('Todoist connection methods', () => {
    it('offers the declared OAuth flow and a personal API token', () => {
        const methods = credentialRequirements('automation-todoist').map(methodFromRequirement);
        expect(methods).toHaveLength(2);
        expect(methods[0]).toMatchObject({
            credential_type: 'todoist_oauth', method_kind: 'oauth',
            oauth_provider: 'todoist',
        });
        expect(methods[0].oauth_scopes).toEqual(['data:delete', 'data:read_write', 'project:delete']);
        expect(methods[1]).toMatchObject({
            credential_type: 'todoist_api_token', method_kind: 'api_key',
        });
        expect(metadata.oauthProviders[0]).toMatchObject({
            provider: 'todoist', scopeSeparator: ',',
            authorizeUrl: 'https://app.todoist.com/oauth/authorize',
        });
    });
});
