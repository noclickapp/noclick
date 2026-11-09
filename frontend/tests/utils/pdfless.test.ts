import { beforeAll, describe, expect, it, vi } from 'vitest';

vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations, getNodeSchema } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';

describe('Pdfless integration', () => {
    beforeAll(() => loadNodeSchemas(['automation-pdfless']));
    it('offers a manually pasted API key', () => {
        expect(getNodeCredentialInfo('automation-pdfless')?.acceptedTypes).toEqual(['pdfless_api_key']);
        expect(getCredentialTypeFromSchemaTitle('PdflessAPIKeyCredential')).toBe('pdfless_api_key');
        expect(getCredentialTypeFromSchemaTitle('Pdfless API Key')).toBe('pdfless_api_key');
        const schema = getNodeSchema('automation-pdfless');
        expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
    });
    it('exposes exactly the three operations published in the v1 contract', () => {
        expect(getAgentToolOperations('automation-pdfless').map(op => op.operation).sort()).toEqual([
            'generate_pdf', 'get_workspace', 'list_document_templates',
        ]);
    });
});
