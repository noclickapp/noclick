import { beforeAll, describe, expect, it, vi } from 'vitest';
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));
import { getAgentToolOperations, getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/ignisign.json';

describe('Ignisign integration metadata', () => {
  beforeAll(() => loadNodeSchemas(['automation-ignisign']));
  it('offers a manual API key connection', () => {
    expect(getNodeCredentialInfo('automation-ignisign')?.acceptedTypes).toEqual(['ignisign_api_key']);
    expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
  });
  it('discovers reads and writes for signing workflows', () => {
    const ops = getAgentToolOperations('automation-ignisign').map(op => op.operation);
    expect(ops).toHaveLength(24);
    expect(ops).toEqual(expect.arrayContaining(['get_application', 'create_signer', 'create_document', 'publish_signature_request']));
  });
});
