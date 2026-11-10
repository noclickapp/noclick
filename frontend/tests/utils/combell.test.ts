import { beforeAll, describe, expect, it, vi } from 'vitest';

vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations, filterConfigForExecution } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/combell.json';

describe('Combell integration metadata', () => {
  beforeAll(() => loadNodeSchemas(['automation-combell']));
  it('offers a manual API key and secret', () => {
    expect(getNodeCredentialInfo('automation-combell')?.acceptedTypes).toEqual(['combell_api_key']);
    expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
    expect(schema.$defs.CombellAPIKeyCredential.required).toEqual(['api_key', 'api_secret']);
    expect(schema.$defs.CombellAPIKeyCredential.properties.credential_type.default).toBe('combell_api_key');
  });
  it('exposes 25 operations and filters fields from other operations', () => {
    const operations = getAgentToolOperations('automation-combell').map(op => op.operation);
    expect(operations).toHaveLength(25);
    expect(operations).toContain('create_dns_record');
    expect(operations).toContain('get_provisioning_job');
    expect(filterConfigForExecution('automation-combell', {
      operation: 'get_domain', domain_name: 'example.com', password: 'irrelevant', account_id: 5,
    })).toEqual({ operation: 'get_domain', domain_name: 'example.com' });
  });
});
