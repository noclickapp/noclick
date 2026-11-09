// Solcast catalog and manual API-key connect regression coverage.
// Keeps the generated credential metadata and operation list usable by the UI.
import { beforeAll, expect, it } from 'vitest';
import { loadNodeSchemas, NODE_SCHEMAS, getNodeCredentialInfo } from '~/utils/nodeSchemas';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';

beforeAll(() => loadNodeSchemas(['automation-solcast']));
it('discovers a manually entered API key and 24 operations', () => {
    const schema = NODE_SCHEMAS['automation-solcast'];
    expect(getNodeCredentialInfo('automation-solcast')?.acceptedTypes).toEqual(['solcast_api_key']);
    expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
    expect(Object.keys(schema.properties.config.discriminator.mapping)).toHaveLength(24);
});
