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
import {
    methodFromRequirement,
    requirementsFromSchema,
} from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/manyrequests.json';

describe('ManyRequests integration consumers', () => {
    beforeAll(() => loadNodeSchemas(['automation-manyrequests']));

    it('discovers manual token auth with both required human inputs', () => {
        expect(
            getNodeCredentialInfo('automation-manyrequests')?.acceptedTypes
        ).toEqual(['manyrequests_api_token']);
        expect(getNodeCredentialInfo('automation-manyrequests')?.label).toBe(
            'ManyRequests API Token'
        );
        expect(
            methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind
        ).toBe('api_key');
        expect(schema.$defs.ManyRequestsAPITokenCredential.required).toEqual([
            'portal_url',
            'api_token',
        ]);
        expect(
            schema.$defs.ManyRequestsAPITokenCredential.properties
                .credential_type.default
        ).toBe('manyrequests_api_token');
    });

    it('exposes the 25 operations and filters foreign operation arguments', () => {
        expect(getAgentToolOperations('automation-manyrequests')).toHaveLength(
            25
        );
        expect(
            filterConfigForExecution('automation-manyrequests', {
                operation: 'get_client',
                client_id: 1,
                service_id: '3',
            })
        ).toEqual({ operation: 'get_client', client_id: 1 });
        const operations = getAgentToolOperations(
            'automation-manyrequests'
        ).map((op) => op.operation);
        expect(operations).toContain('create_request');
        expect(operations).toContain('create_time_entry');
        expect(operations).toContain('update_organization');
    });
});
