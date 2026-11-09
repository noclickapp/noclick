import { beforeAll, describe, expect, it, vi } from 'vitest';
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';

describe('Caspio integration metadata', () => {
    beforeAll(() => loadNodeSchemas(['automation-caspio']));

    it('offers a manually connected bearer token', () => {
        const info = getNodeCredentialInfo('automation-caspio');
        expect(info?.acceptedTypes).toEqual(['caspio_bearer_token']);
        expect(getCredentialTypeFromSchemaTitle('CaspioBearerTokenCredential')).toBe('caspio_bearer_token');
        expect(getCredentialTypeFromSchemaTitle('Caspio Bearer Token')).toBe('caspio_bearer_token');
    });

    it('exposes the table, view and task operations', () => {
        const operations = getAgentToolOperations('automation-caspio').map(op => op.operation);
        expect(operations).toHaveLength(19);
        expect(operations).toEqual(expect.arrayContaining([
            'list_tables', 'get_table_field', 'list_table_records', 'create_table_record',
            'update_table_record', 'delete_table_record', 'get_view_record', 'run_task', 'get_task_run',
        ]));
    });
});
