import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations, filterConfigForExecution } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { invalidateCredentialsCache, upsertCredentialsIntoCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/pingdom.json';

describe('Pingdom credential and operation metadata', () => {
  beforeAll(() => loadNodeSchemas(['automation-pingdom']));
  beforeEach(() => invalidateCredentialsCache());
  it('offers a manual API token with the provider label', () => {
    expect(getNodeCredentialInfo('automation-pingdom')?.acceptedTypes).toEqual(['pingdom_api_token']);
    expect(getNodeCredentialInfo('automation-pingdom')?.label).toBe('Pingdom API Token');
    expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
    expect(getCredentialTypeFromSchemaTitle('PingdomAPITokenCredential')).toBe('pingdom_api_token');
    expect(getCredentialTypeFromSchemaTitle('Pingdom API Token')).toBe('pingdom_api_token');
  });
  it('selects an owned token and excludes other providers', () => {
    upsertCredentialsIntoCache([
      { id: 'foreign', name: 'Other', credential_type: 'staffbase_api_token', owned_by_me: true },
      { id: 'display', name: 'Display', credential_type: 'pingdom_api_token', owned_by_me: false },
      { id: 'owned', name: 'Pingdom', credential_type: 'pingdom_api_token', owned_by_me: true },
    ]);
    expect(autoSelectCredentialFromCache('automation-pingdom')).toEqual({ pingdom_api_token: 'owned' });
  });
  it('exposes 20 operations and keeps update fields local to the operation', () => {
    expect(getAgentToolOperations('automation-pingdom')).toHaveLength(20);
    expect(filterConfigForExecution('automation-pingdom', {
      operation: 'update_check', check_id: 100, paused: false, maintenance_id: 456,
    })).toEqual({ operation: 'update_check', check_id: 100, paused: false });
  });
});
