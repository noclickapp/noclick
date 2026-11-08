import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations, filterConfigForExecution } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { invalidateCredentialsCache, upsertCredentialsIntoCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';

const schema = JSON.parse(readFileSync(join(__dirname, '../../app/schemas/nodes/webscraping-ai.json'), 'utf8'));

describe('WebScraping.AI integration consumers', () => {
  beforeAll(() => loadNodeSchemas(['automation-webscraping-ai']));
  beforeEach(() => invalidateCredentialsCache());

  it('offers a pasted API key with the provider label and correct method kind', () => {
    expect(getNodeCredentialInfo('automation-webscraping-ai')?.acceptedTypes).toEqual(['webscraping_ai_api_key']);
    expect(getCredentialTypeFromSchemaTitle('WebScraping.AI API Key')).toBe('webscraping_ai_api_key');
    expect(getCredentialTypeFromSchemaTitle('WebscrapingAiAPIKeyCredential')).toBe('webscraping_ai_api_key');
    expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
  });

  it('selects only an owned WebScraping.AI key', () => {
    upsertCredentialsIntoCache([
      { id: 'foreign', name: 'Foreign', credential_type: 'staffbase_api_token', owned_by_me: true },
      { id: 'display', name: 'Display', credential_type: 'webscraping_ai_api_key', owned_by_me: false },
      { id: 'owned', name: 'Owned', credential_type: 'webscraping_ai_api_key', owned_by_me: true },
    ]);
    expect(autoSelectCredentialFromCache('automation-webscraping-ai')).toEqual({ webscraping_ai_api_key: 'owned' });
  });

  it('offers ten published operations and filters fields for the chosen operation', () => {
    const operations = getAgentToolOperations('automation-webscraping-ai').map(op => op.operation);
    expect(operations).toHaveLength(10);
    expect(operations).toContain('get_account');
    expect(operations).toContain('get_structured_data');
    expect(filterConfigForExecution('automation-webscraping-ai', {
      operation: 'get_account', url: 'https://example.com', fields_json: '{}',
    })).toEqual({ operation: 'get_account' });
  });
});
