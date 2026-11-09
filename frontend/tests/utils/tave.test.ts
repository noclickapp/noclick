import { beforeAll, describe, expect, it, vi } from 'vitest';

vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));
import { getNodeCredentialInfo, getAgentToolOperations, loadNodeSchemas } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/tave.json';

describe('Tave catalog and manual connection', () => {
    beforeAll(() => loadNodeSchemas(['automation-tave']));

    it('discovers the API key with a manually fillable field', () => {
        expect(getNodeCredentialInfo('automation-tave')?.acceptedTypes).toEqual(['tave_api_key']);
        expect(getCredentialTypeFromSchemaTitle('Tave API Key')).toBe('tave_api_key');
        expect(getCredentialTypeFromSchemaTitle('TaveAPIKeyCredential')).toBe('tave_api_key');
        const method = methodFromRequirement(requirementsFromSchema(schema)[0]);
        expect(method.method_kind).toBe('api_key');
        expect(schema.$defs.TaveAPIKeyCredential.required).toEqual(['api_key']);
    });

    it('makes all 25 operations available to agents', () => {
        const operations = getAgentToolOperations('automation-tave').map(op => op.operation);
        expect(operations).toHaveLength(25);
        expect(operations).toEqual(expect.arrayContaining(['get_studio', 'create_contact', 'update_job', 'create_event', 'update_task', 'create_note', 'list_invoices']));
    });
});
