import { beforeAll, describe, expect, it, vi } from 'vitest';

vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations, getNodeSchema } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';

describe('TimeCamp integration metadata', () => {
  beforeAll(() => loadNodeSchemas(['automation-timecamp']));
  it('discovers the pasted token credential and its human label', () => {
    expect(getNodeCredentialInfo('automation-timecamp')?.acceptedTypes).toEqual(['timecamp_api_token']);
    expect(getCredentialTypeFromSchemaTitle('TimecampAPITokenCredential')).toBe('timecamp_api_token');
    expect(getCredentialTypeFromSchemaTitle('Timecamp API Token')).toBe('timecamp_api_token');
    const schema = getNodeSchema('automation-timecamp');
    expect(schema).toBeTruthy();
    expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
  });
  it('offers the 21 published read and write operations', () => {
    const operations = getAgentToolOperations('automation-timecamp').map(op => op.operation);
    expect(operations).toHaveLength(21);
    expect(operations).toEqual(expect.arrayContaining([
      'get_me', 'list_tasks', 'create_task', 'update_task', 'delete_task',
      'list_entries', 'create_entry', 'update_entry', 'delete_entry',
      'get_timer_status', 'start_timer', 'stop_timer', 'create_tag', 'list_tag_lists',
    ]));
  });
});
