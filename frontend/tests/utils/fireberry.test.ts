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
import schema from '~/schemas/nodes/fireberry.json';

describe('Fireberry integration metadata', () => {
    beforeAll(() => loadNodeSchemas(['automation-fireberry']));
    it('discovers the pasted token with its human label and API key method', () => {
        expect(
            getNodeCredentialInfo('automation-fireberry')?.acceptedTypes
        ).toEqual(['fireberry_api_token']);
        expect(getNodeCredentialInfo('automation-fireberry')?.label).toBe(
            'Fireberry API Token'
        );
        expect(getCredentialTypeFromSchemaTitle('Fireberry API Token')).toBe(
            'fireberry_api_token'
        );
        expect(
            methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind
        ).toBe('api_key');
    });
    it('exposes 20 record operations and filters unrelated fields', () => {
        const operations = getAgentToolOperations('automation-fireberry').map(
            (op) => op.operation
        );
        expect(operations).toHaveLength(20);
        expect(operations).toContain('list_opportunities');
        expect(operations).toContain('create_task');
        expect(
            filterConfigForExecution('automation-fireberry', {
                operation: 'get_account',
                record_id: 'abc',
                firstname: 'Jane',
            })
        ).toEqual({ operation: 'get_account', record_id: 'abc' });
    });
});
