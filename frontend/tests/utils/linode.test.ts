// Verifies Linode's generated credential metadata reaches native consumers.
// This protects manual connection selection and the agent's operation catalogue.
import { beforeAll, describe, expect, it, vi } from 'vitest';
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations, filterConfigForExecution } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/linode.json';

describe('Linode native consumers', () => {
  beforeAll(() => loadNodeSchemas(['automation-linode']));
  it('discovers the manual token method and both credential aliases', () => {
    expect(getNodeCredentialInfo('automation-linode')?.acceptedTypes).toEqual(['linode_personal_access_token']);
    expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
    expect(getCredentialTypeFromSchemaTitle('LinodeTokenCredential')).toBe('linode_personal_access_token');
    expect(getCredentialTypeFromSchemaTitle('Linode Personal Access Token')).toBe('linode_personal_access_token');
  });
  it('exposes all 22 operations and retains only fields for the selected operation', () => {
    expect(getAgentToolOperations('automation-linode')).toHaveLength(22);
    expect(filterConfigForExecution('automation-linode', { operation: 'update_record', domain_id: 1234, record_id: 123456, ttl_sec: 3600, linode_id: 123 })).toEqual({ operation: 'update_record', domain_id: 1234, record_id: 123456, ttl_sec: 3600 });
  });
});
