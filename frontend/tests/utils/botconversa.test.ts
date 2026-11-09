import { beforeAll, expect, it } from 'vitest';
import { loadNodeSchemas, NODE_SCHEMAS, getNodeCredentialInfo } from '~/utils/nodeSchemas';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';

beforeAll(() => loadNodeSchemas(['automation-botconversa']));
it('offers a pasted API key and the 24 BotConversa operations', () => {
    const schema = NODE_SCHEMAS['automation-botconversa'];
    expect(getNodeCredentialInfo('automation-botconversa')?.acceptedTypes).toEqual(['botconversa_api_key']);
    expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
    expect(Object.keys(schema.properties.config.discriminator.mapping)).toHaveLength(24);
});
