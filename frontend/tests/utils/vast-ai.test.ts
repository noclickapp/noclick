// Vast.ai must be discoverable with its manual API key on every connect surface.
// These assertions cover generated credential metadata and agent operation discovery.
import { beforeAll, expect, it } from 'vitest';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations, getNodeSchema } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';

beforeAll(() => loadNodeSchemas(['automation-vast-ai']));
it('offers a manually connected Vast Ai API key', () => {
    const schema = getNodeSchema('automation-vast-ai');
    expect(getNodeCredentialInfo('automation-vast-ai')?.acceptedTypes).toEqual(['vast_ai_api_key']);
    expect(getNodeCredentialInfo('automation-vast-ai')?.label).toBe('Vast Ai API Key');
    expect(methodFromRequirement(requirementsFromSchema(schema)[0])).toMatchObject({ method_kind: 'api_key', is_oauth: false });
    expect(getCredentialTypeFromSchemaTitle('Vast Ai API Key')).toBe('vast_ai_api_key');
});
it('makes 22 read and write operations available to agents', () => {
    const operations = getAgentToolOperations('automation-vast-ai').map(op => op.operation);
    expect(operations).toHaveLength(22);
    expect(operations).toContain('get_current_user');
    expect(operations).toContain('create_instance');
    expect(operations).toContain('manage_instance');
    expect(operations).toContain('rent_volume');
});
