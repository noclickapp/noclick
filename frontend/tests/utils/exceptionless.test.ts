import { beforeAll, describe, expect, it, vi } from 'vitest';
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations, filterConfigForExecution } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/exceptionless.json';

describe('Exceptionless integration metadata', () => {
    beforeAll(() => loadNodeSchemas(['automation-exceptionless']));
    it('offers a manually pasted user token with generated aliases', () => {
        expect(getNodeCredentialInfo('automation-exceptionless')?.acceptedTypes).toEqual(['exceptionless_user_token']);
        expect(getNodeCredentialInfo('automation-exceptionless')?.label).toBe('Exceptionless User Token');
        expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
        expect(getCredentialTypeFromSchemaTitle('ExceptionlessUserTokenCredential')).toBe('exceptionless_user_token');
        expect(getCredentialTypeFromSchemaTitle('Exceptionless User Token')).toBe('exceptionless_user_token');
    });
    it('discovers twenty operations and keeps only the selected operation fields', () => {
        const operations = getAgentToolOperations('automation-exceptionless').map(op => op.operation);
        expect(operations).toHaveLength(20);
        expect(operations).toContain('mark_stacks_fixed');
        expect(operations).toContain('create_project');
        expect(filterConfigForExecution('automation-exceptionless', { operation: 'get_event', event_id: '0123456789abcdef01234567', name: 'unrelated' }))
            .toEqual({ operation: 'get_event', event_id: '0123456789abcdef01234567' });
    });
});
