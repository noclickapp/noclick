import { beforeAll, describe, expect, it, vi } from 'vitest';
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations, filterConfigForExecution } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/infisical.json';

describe('Infisical discovery', () => {
  beforeAll(() => loadNodeSchemas(['automation-infisical']));
  it('offers a manually connected API token with discovered aliases', () => {
    expect(getNodeCredentialInfo('automation-infisical')?.acceptedTypes).toEqual(['infisical_api_token']);
    expect(getCredentialTypeFromSchemaTitle('InfisicalTokenCredential')).toBe('infisical_api_token');
    expect(getCredentialTypeFromSchemaTitle('Infisical API Token')).toBe('infisical_api_token');
    expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
  });
  it('exposes reads and writes and filters other operations fields', () => {
    const operations = getAgentToolOperations('automation-infisical').map(op => op.operation);
    expect(operations).toHaveLength(20);
    expect(operations).toContain('create_secret');
    expect(operations).toContain('list_projects');
    expect(filterConfigForExecution('automation-infisical', { operation: 'get_project', project_id: 'project-1', secret_value: 'private' })).toEqual({ operation: 'get_project', project_id: 'project-1' });
  });
});
