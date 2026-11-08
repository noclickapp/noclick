import { beforeAll, describe, expect, it, vi } from 'vitest';
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations, getNodeSchema } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';

describe('Namsor integration metadata', () => {
  beforeAll(() => loadNodeSchemas(['automation-namsor']));
  it('discovers the manually pasted key method', () => {
    expect(getNodeCredentialInfo('automation-namsor')?.acceptedTypes).toEqual(['namsor_api_key']);
    expect(getCredentialTypeFromSchemaTitle('Namsor API Key')).toBe('namsor_api_key');
    const schema = getNodeSchema('automation-namsor');
    expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
  });
  it('offers 25 contract operations including explicit privacy writes', () => {
    const operations = getAgentToolOperations('automation-namsor').map(op => op.operation);
    expect(operations).toHaveLength(25);
    expect(operations).toEqual(expect.arrayContaining(['get_api_key_info', 'parse_name', 'parse_names_batch', 'set_learning', 'set_anonymization']));
  });
});
