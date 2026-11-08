import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations, filterConfigForExecution } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { invalidateCredentialsCache, upsertCredentialsIntoCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/debounce.json';

describe('DeBounce native integration', () => {
  beforeAll(() => loadNodeSchemas(['automation-debounce']));
  beforeEach(() => invalidateCredentialsCache());
  it('maps its credential title and method to a pasted API key', () => {
    expect(getNodeCredentialInfo('automation-debounce')?.acceptedTypes).toEqual(['debounce_api_key']);
    expect(getCredentialTypeFromSchemaTitle('DebounceAPIKeyCredential')).toBe('debounce_api_key');
    expect(getCredentialTypeFromSchemaTitle('Debounce API Key')).toBe('debounce_api_key');
    expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
  });
  it('selects the owned DeBounce credential', () => {
    upsertCredentialsIntoCache([
      { id: 'foreign', name: 'Foreign', credential_type: 'staffbase_api_token', owned_by_me: true },
      { id: 'owned', name: 'DeBounce', credential_type: 'debounce_api_key', owned_by_me: true },
    ]);
    expect(autoSelectCredentialFromCache('automation-debounce')).toEqual({ debounce_api_key: 'owned' });
  });
  it('exposes ten actions and isolates selected operation fields', () => {
    expect(getAgentToolOperations('automation-debounce')).toHaveLength(10);
    expect(filterConfigForExecution('automation-debounce', {
      operation: 'upload_bulk_list', url: 'https://example.com/emails.csv', email: 'other@example.com',
    })).toEqual({ operation: 'upload_bulk_list', url: 'https://example.com/emails.csv' });
  });
});
