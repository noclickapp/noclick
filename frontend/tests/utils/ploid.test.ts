import { beforeAll, describe, expect, it, vi } from 'vitest';
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations, getNodeSchema } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';

describe('Ploid integration', () => {
    beforeAll(() => loadNodeSchemas(['automation-ploid']));
    it('offers a manually pasted API key with discoverable aliases', () => {
        expect(getNodeCredentialInfo('automation-ploid')?.acceptedTypes).toEqual(['ploid_api_key']);
        expect(getCredentialTypeFromSchemaTitle('PloidAPIKeyCredential')).toBe('ploid_api_key');
        expect(getCredentialTypeFromSchemaTitle('Ploid API Key')).toBe('ploid_api_key');
        expect(methodFromRequirement(requirementsFromSchema(getNodeSchema('automation-ploid'))[0]).method_kind).toBe('api_key');
    });
    it('discovers all 25 contract operations', () => {
        const operations = getAgentToolOperations('automation-ploid').map(op => op.operation);
        expect(operations).toHaveLength(25);
        expect(operations).toEqual(expect.arrayContaining(['create_monitor', 'update_monitor', 'search_people', 'create_dataset', 'get_account_profile']));
    });
});
