import { beforeAll, describe, expect, it, vi } from 'vitest';
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({
    valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() },
}));
import {
    loadNodeSchemas,
    getNodeCredentialInfo,
    getAgentToolOperations,
    filterConfigForExecution,
} from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import {
    methodFromRequirement,
    requirementsFromSchema,
} from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/isn.json';

describe('ISN integration metadata', () => {
    beforeAll(() => loadNodeSchemas(['automation-isn']));
    it('offers a manual API key credential with both title aliases', () => {
        expect(getNodeCredentialInfo('automation-isn')?.acceptedTypes).toEqual([
            'isn_api_key',
        ]);
        expect(getCredentialTypeFromSchemaTitle('ISNAPIKeyCredential')).toBe(
            'isn_api_key'
        );
        expect(getCredentialTypeFromSchemaTitle('ISN API Key')).toBe(
            'isn_api_key'
        );
        expect(
            methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind
        ).toBe('api_key');
    });
    it('exposes supported actions and isolates fields for the selected operation', () => {
        expect(getAgentToolOperations('automation-isn')).toHaveLength(22);
        expect(
            filterConfigForExecution('automation-isn', {
                operation: 'get_order',
                order_id: 'order-42',
                all_controls: false,
                client_id: 'client-42',
                name: 'Other operation',
            })
        ).toEqual({
            operation: 'get_order',
            order_id: 'order-42',
            all_controls: false,
        });
    });
});
