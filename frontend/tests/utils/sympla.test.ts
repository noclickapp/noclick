import { beforeAll, describe, expect, it, vi } from 'vitest';

vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations, getNodeSchema } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';

describe('Sympla integration metadata', () => {
  beforeAll(() => loadNodeSchemas(['automation-sympla']));
  it('discovers the pasted token credential and labels', () => {
    expect(getNodeCredentialInfo('automation-sympla')?.acceptedTypes).toEqual(['sympla_api_token']);
    expect(getCredentialTypeFromSchemaTitle('SymplaTokenCredential')).toBe('sympla_api_token');
    expect(getCredentialTypeFromSchemaTitle('Sympla API Token')).toBe('sympla_api_token');
    const schema = getNodeSchema('automation-sympla');
    expect(schema).toBeTruthy();
    expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
  });
  it('marks the two polling operations as triggers', () => {
    const schema = getNodeSchema('automation-sympla') as any;
    for (const name of ['SymplaOnNewOrUpdatedOrderConfig', 'SymplaOnNewOrUpdatedParticipantConfig']) {
      expect(schema.$defs[name]['x-requires-webhook']).toBe(true);
      expect(schema.$defs[name].properties.operation['x-is-trigger']).toBe(true);
    }
  });
  it('offers the complete v1.6.0 read and check-in operation set', () => {
    const operations = getAgentToolOperations('automation-sympla').map(op => op.operation);
    expect(operations).toHaveLength(15);
    expect(operations).toEqual(expect.arrayContaining(['list_events', 'get_order', 'list_order_participants', 'list_presentations', 'check_in_participant', 'check_in_by_ticket', 'check_in_qr_code']));
  });
});
