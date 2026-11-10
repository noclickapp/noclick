import { beforeAll, describe, expect, it, vi } from 'vitest';
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations, filterConfigForExecution } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/samdock.json';

describe('Samdock native metadata', () => {
  beforeAll(() => loadNodeSchemas(['automation-samdock']));
  it('offers the manual token connection', () => {
    expect(getNodeCredentialInfo('automation-samdock')?.acceptedTypes).toEqual(['samdock_api_token']);
    const method = methodFromRequirement(requirementsFromSchema(schema)[0]);
    expect(method.method_kind).toBe('api_key');
    expect(method.credential_fields?.map(f => f.name)).toEqual(['api_token']);
  });
  it('discovers all 25 operations and scopes fields to the selected operation', () => {
    const operations = getAgentToolOperations('automation-samdock').map(op => op.operation);
    expect(operations).toHaveLength(25);
    expect(operations).toContain('create_person');
    expect(operations).toContain('update_task');
    expect(filterConfigForExecution('automation-samdock', { operation: 'get_deal', id: '1', tenant_id: 'foreign', limit: 100 })).toEqual({ operation: 'get_deal', id: '1' });
  });
});
