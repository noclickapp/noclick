import { beforeAll, describe, expect, it, vi } from 'vitest';

vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations, getNodeSchema } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';

describe('DocuGenerate integration', () => {
    beforeAll(() => loadNodeSchemas(['automation-docugenerate']));
    it('offers one pasted API key with discoverable credential aliases', () => {
        expect(getNodeCredentialInfo('automation-docugenerate')?.acceptedTypes).toEqual(['docugenerate_api_key']);
        expect(getCredentialTypeFromSchemaTitle('DocugenerateAPIKey')).toBe('docugenerate_api_key');
        expect(getCredentialTypeFromSchemaTitle('Docugenerate API Key')).toBe('docugenerate_api_key');
        const schema = getNodeSchema('automation-docugenerate');
        expect(schema).toBeTruthy();
        expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
    });
    it('exposes all ten operations in API 1.9.1', () => {
        expect(getAgentToolOperations('automation-docugenerate').map(op => op.operation).sort()).toEqual([
            'create_template', 'delete_document', 'delete_template', 'generate_document', 'get_document',
            'get_template', 'list_documents', 'list_templates', 'update_document', 'update_template',
        ]);
    });
});
