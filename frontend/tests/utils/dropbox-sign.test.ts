import { beforeAll, describe, expect, it, vi } from 'vitest';
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({
    valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() },
}));
import {
    loadNodeSchemas,
    getNodeCredentialInfo,
    getAgentToolOperations,
} from '~/utils/nodeSchemas';
import {
    methodFromRequirement,
    requirementsFromSchema,
} from '~/components/credential/credentialMethods';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import schema from '~/schemas/nodes/dropbox-sign.json';

describe('Dropbox Sign discovery', () => {
    beforeAll(() => loadNodeSchemas(['automation-dropbox-sign']));
    it('offers the correctly labeled pasted API key', () => {
        expect(
            getNodeCredentialInfo('automation-dropbox-sign')?.acceptedTypes
        ).toEqual(['dropbox_sign_api_key']);
        expect(getNodeCredentialInfo('automation-dropbox-sign')?.label).toBe(
            'Dropbox Sign API Key'
        );
        expect(
            methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind
        ).toBe('api_key');
        expect(
            getCredentialTypeFromSchemaTitle('DropboxSignAPIKeyCredential')
        ).toBe('dropbox_sign_api_key');
        expect(getCredentialTypeFromSchemaTitle('Dropbox Sign API Key')).toBe(
            'dropbox_sign_api_key'
        );
    });
    it('exposes signature request and template reads and writes', () => {
        const operations = getAgentToolOperations(
            'automation-dropbox-sign'
        ).map((op) => op.operation);
        expect(operations).toHaveLength(16);
        expect(operations).toEqual(
            expect.arrayContaining([
                'send_signature_request',
                'send_with_template',
                'list_signature_requests',
                'get_signature_request_file_url',
                'get_template',
                'cancel_signature_request',
            ])
        );
    });
});
