import { beforeAll, describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { loadNodeSchemas } from '~/utils/nodeSchemas';
import metadata from '~/schemas/nodeMeta/clover.json';

beforeAll(() => loadNodeSchemas(['automation-clover']));
describe('Clover connection methods', () => {
    it('offers a merchant API token and the declared OAuth flow', () => {
        const methods = credentialRequirements('automation-clover').map(methodFromRequirement);
        expect(methods).toHaveLength(2);
        expect(methods).toEqual(expect.arrayContaining([
            expect.objectContaining({ credential_type: 'clover_api_token', method_kind: 'api_key' }),
            expect.objectContaining({ credential_type: 'clover_oauth', method_kind: 'oauth', oauth_provider: 'clover' }),
        ]));
        expect(metadata.oauthProviders[0]).toMatchObject({
            provider: 'clover', authorizeUrl: 'https://www.{clover_domain}/oauth/v2/authorize',
            contextFields: { merchant_id: { source: 'callback' }, clover_domain: { source: 'input' } },
        });
    });
});
