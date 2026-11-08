import { beforeAll, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations, filterConfigForExecution } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
const schema = JSON.parse(readFileSync(join(__dirname, '../../app/schemas/nodes/nanonets-ocr.json'), 'utf8'));

describe('Nanonets OCR integration', () => {
  beforeAll(() => loadNodeSchemas(['automation-nanonets-ocr']));
  it('connects with a pasted API key', () => {
    expect(getNodeCredentialInfo('automation-nanonets-ocr')?.acceptedTypes).toEqual(['nanonets_ocr_api_key']);
    expect(getCredentialTypeFromSchemaTitle('Nanonets OCR API Key')).toBe('nanonets_ocr_api_key');
    expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
  });
  it('offers all 17 published operations and keeps only the selected operation fields', () => {
    expect(getAgentToolOperations('automation-nanonets-ocr')).toHaveLength(17);
    expect(filterConfigForExecution('automation-nanonets-ocr', {
      operation: 'list_classification_models', model_id: 'unused', urls: ['https://example.com/a.pdf'],
    })).toEqual({ operation: 'list_classification_models' });
  });
});
