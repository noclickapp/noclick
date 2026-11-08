import { beforeAll, expect, it } from 'vitest';
import { loadNodeSchemas, NODE_SCHEMAS, getNodeCredentialInfo } from '~/utils/nodeSchemas';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';

beforeAll(() => loadNodeSchemas(['automation-android-texter']));

it('discovers a pasted API key and the 25 native Android Texter operations', () => {
    const schema = NODE_SCHEMAS['automation-android-texter'];
    expect(getNodeCredentialInfo('automation-android-texter')?.acceptedTypes).toEqual(['android_texter_api_key']);
    const method = methodFromRequirement(requirementsFromSchema(schema)[0]);
    expect(method.method_kind).toBe('api_key');
    expect(method.is_oauth).toBe(false);
    expect(Object.keys(schema.properties.config.discriminator.mapping)).toHaveLength(25);
});
