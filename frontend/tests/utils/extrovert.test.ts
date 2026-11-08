import { beforeAll, describe, expect, it, vi } from 'vitest';

vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations, filterConfigForExecution } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import schema from '~/schemas/nodes/extrovert.json';

describe('Extrovert native credential and operations', () => {
  beforeAll(() => loadNodeSchemas(['automation-extrovert']));
  it('offers the pasted API key method on native consumers', () => {
    expect(getNodeCredentialInfo('automation-extrovert')?.acceptedTypes).toEqual(['extrovert_api_key']);
    expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
    expect(getCredentialTypeFromSchemaTitle('Extrovert API Key')).toBe('extrovert_api_key');
  });
  it('lists the 25 actions and strips fields from other actions', () => {
    expect(getAgentToolOperations('automation-extrovert')).toHaveLength(25);
    expect(filterConfigForExecution('automation-extrovert', {
      operation: 'send_reply', dm_id: 'reply', mode: 'queued', owner_id: 'owner', text: 'unrelated',
    })).toEqual({ operation: 'send_reply', dm_id: 'reply', mode: 'queued' });
  });
});
