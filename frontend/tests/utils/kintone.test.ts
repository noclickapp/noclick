import { beforeAll, describe, expect, it, vi } from 'vitest';
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/kintone.json';

describe('Kintone integration metadata', () => {
  beforeAll(() => loadNodeSchemas(['automation-kintone']));
  it('offers a pasted API token with tenant and app context', () => {
    expect(getNodeCredentialInfo('automation-kintone')?.acceptedTypes).toEqual(['kintone_api_token']);
    expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
    expect(getCredentialTypeFromSchemaTitle('KintoneAPITokenCredential')).toBe('kintone_api_token');
    expect(getCredentialTypeFromSchemaTitle('Kintone API Token')).toBe('kintone_api_token');
  });
  it('discovers record reads and writes, comments, process actions and cursor export', () => {
    const operations = getAgentToolOperations('automation-kintone').map(op => op.operation);
    expect(operations).toHaveLength(19);
    expect(operations).toEqual(expect.arrayContaining(['get_app', 'get_record', 'create_record', 'update_records', 'delete_records', 'add_comment', 'get_cursor', 'update_status']));
  });
});
