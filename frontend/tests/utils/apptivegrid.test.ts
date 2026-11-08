import { beforeAll, expect, it, vi } from 'vitest';

vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({
    valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() },
}));
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import {
    getNodeCredentialInfo,
    getNodeSchema,
    getAgentToolOperations,
    loadNodeSchemas,
} from '~/utils/nodeSchemas';
import {
    requirementsFromSchema,
    methodFromRequirement,
} from '~/components/credential/credentialMethods';

beforeAll(() => loadNodeSchemas(['automation-apptivegrid']));
it('discovers one manually entered API key method and its schema aliases', () => {
    expect(
        getCredentialTypeFromSchemaTitle('ApptivegridAPIKeyCredential')
    ).toBe('apptivegrid_api_key');
    expect(getCredentialTypeFromSchemaTitle('Apptivegrid API Key')).toBe(
        'apptivegrid_api_key'
    );
    expect(
        getNodeCredentialInfo('automation-apptivegrid')?.acceptedTypes
    ).toEqual(['apptivegrid_api_key']);
    const requirements = requirementsFromSchema(
        getNodeSchema('automation-apptivegrid')
    );
    expect(requirements).toHaveLength(1);
    expect(methodFromRequirement(requirements[0])).toMatchObject({
        method_kind: 'api_key',
        is_oauth: false,
    });
});
it('offers the account read and space, grid and entry automations', () => {
    const operations = getAgentToolOperations('automation-apptivegrid').map(
        (op) => op.operation
    );
    expect(operations).toHaveLength(20);
    expect(operations).toEqual(
        expect.arrayContaining([
            'get_user',
            'list_spaces',
            'create_grid',
            'get_grid_schema',
            'create_entry',
            'partial_update_entry',
            'delete_entry',
            'list_views',
            'list_forms',
        ])
    );
});
