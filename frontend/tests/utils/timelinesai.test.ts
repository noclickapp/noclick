import { beforeAll, expect, it } from 'vitest';
import { loadNodeSchemas, NODE_SCHEMAS, getNodeCredentialInfo } from '~/utils/nodeSchemas';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';
beforeAll(() => loadNodeSchemas(['automation-timelinesai']));
it('discovers a native API token and 23 published operations', () => {
    const schema = NODE_SCHEMAS['automation-timelinesai'];
    expect(getNodeCredentialInfo('automation-timelinesai')?.acceptedTypes).toEqual(['timelinesai_api_token']);
    expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
    expect(Object.keys(schema.properties.config.discriminator.mapping)).toHaveLength(23);
});
