import { beforeAll, expect, it } from 'vitest';
import { loadNodeSchemas, NODE_SCHEMAS, getNodeCredentialInfo } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { BloomGrowthNode } from '~/components/workflow/nodes/integrations/bloom-growth';

beforeAll(() => loadNodeSchemas(['automation-bloom-growth']));
it('discovers one manually entered token and 25 operations in productivity', () => {
    const schema = NODE_SCHEMAS['automation-bloom-growth'];
    expect(getNodeCredentialInfo('automation-bloom-growth')?.acceptedTypes).toEqual(['bloom_growth_api_token']);
    const requirements = requirementsFromSchema(schema);
    expect(requirements).toHaveLength(1);
    expect(methodFromRequirement(requirements[0])).toMatchObject({
        credential_type: 'bloom_growth_api_token', method_kind: 'api_key', is_oauth: false,
    });
    expect(Object.keys(schema.properties.config.discriminator.mapping)).toHaveLength(25);
    expect(schema.$defs.BloomGrowthTokenCredential.required).toEqual(['api_token']);
    expect(schema.$defs.BloomGrowthTokenCredential.properties.credential_type.default).toBe('bloom_growth_api_token');
    expect(BloomGrowthNode.category).toBe('productivity');
});
