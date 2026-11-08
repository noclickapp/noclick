import { beforeAll, describe, expect, it } from 'vitest';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/timely.json';

describe('Timely credential and operations', () => {
  beforeAll(() => loadNodeSchemas(['automation-timely']));
  it('offers a pasted bearer token with workspace context', () => {
    expect(getNodeCredentialInfo('automation-timely')?.acceptedTypes).toEqual(['timely_token']);
    expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
  });
  it('exposes the contracted reads and writes', () => {
    const ops = getAgentToolOperations('automation-timely').map(op => op.operation);
    expect(ops).toHaveLength(18);
    expect(ops).toEqual(expect.arrayContaining(['get_current_user', 'create_client', 'create_project', 'create_time_entry', 'start_timer', 'stop_timer']));
  });
});
