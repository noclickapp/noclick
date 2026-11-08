import { beforeAll, describe, expect, it, vi } from 'vitest';
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations, filterConfigForExecution } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/wachete.json';

describe('Wachete native metadata', () => {
  beforeAll(() => loadNodeSchemas(['automation-wachete']));
  it('offers a manual API token with both credential aliases', () => {
    expect(getNodeCredentialInfo('automation-wachete')?.acceptedTypes).toEqual(['wachete_api_token']);
    expect(getNodeCredentialInfo('automation-wachete')?.label).toBe('Wachete API Token');
    expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
    expect(getCredentialTypeFromSchemaTitle('WacheteTokenCredential')).toBe('wachete_api_token');
    expect(getCredentialTypeFromSchemaTitle('Wachete API Token')).toBe('wachete_api_token');
  });
  it('discovers the twelve operations and filters fields for the selected operation', () => {
    const operations = getAgentToolOperations('automation-wachete').map(op => op.operation);
    expect(operations).toHaveLength(12);
    expect(operations).toContain('save_monitor');
    expect(operations).toContain('list_folder_contents');
    expect(filterConfigForExecution('automation-wachete', { operation: 'delete_monitor', monitor_id: 'task-1', name: 'unrelated' }))
      .toEqual({ operation: 'delete_monitor', monitor_id: 'task-1' });
  });
});
