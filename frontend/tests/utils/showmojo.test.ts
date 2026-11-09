// Check ShowMojo discovery and the manual account-token connection method.
// The schema and metadata must expose the same operations as the backend.
import { beforeAll, expect, it } from 'vitest';
import { loadNodeSchemas, NODE_SCHEMAS, getNodeCredentialInfo } from '~/utils/nodeSchemas';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';

beforeAll(() => loadNodeSchemas(['automation-showmojo']));

it('discovers a pasted ShowMojo API token and 12 actions plus a poll trigger', () => {
    const schema = NODE_SCHEMAS['automation-showmojo'];
    expect(getNodeCredentialInfo('automation-showmojo')?.acceptedTypes).toEqual(['showmojo_api_token']);
    const method = methodFromRequirement(requirementsFromSchema(schema)[0]);
    expect(method.method_kind).toBe('api_key');
    expect(method.is_oauth).toBe(false);
    expect(Object.keys(schema.properties.config.discriminator.mapping)).toHaveLength(13);
});
