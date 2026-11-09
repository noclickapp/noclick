// Verifies the SPOTIO credential form is a manual token connection.
// It also checks that the generated operation catalog exposes record reads and writes.
import { beforeAll, expect, it } from 'vitest';
import { getAgentToolOperations, getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/spotio2.json';

beforeAll(() => loadNodeSchemas(['automation-spotio2']));

it('offers a manual SPOTIO API token', () => {
    expect(getNodeCredentialInfo('automation-spotio2')?.acceptedTypes).toEqual(['spotio2_api_token']);
    expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
});

it('exposes twenty SPOTIO operations', () => {
    const operations = getAgentToolOperations('automation-spotio2').map(op => op.operation);
    expect(operations).toHaveLength(20);
    expect(operations).toContain('create_record');
    expect(operations).toContain('update_record');
    expect(operations).toContain('get_appointment');
});
