import { beforeAll, describe, expect, it } from 'vitest';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { MEQRQRCodeNode } from '~/components/workflow/nodes/integrations/me-qr-qr-code';

describe('ME-QR native integration', () => {
    beforeAll(() => loadNodeSchemas(['automation-me-qr-qr-code']));
    it('discovers its category, token credential and 21 operations', async () => {
        const { default: schema } = await import('~/schemas/nodes/me-qr-qr-code.json');
        expect(MEQRQRCodeNode.category).toBe('marketing');
        expect(MEQRQRCodeNode.label).toBe('ME-QR QR Code');
        expect(getNodeCredentialInfo('automation-me-qr-qr-code')?.acceptedTypes).toEqual(['me_qr_qr_code_api_token']);
        expect(requirementsFromSchema(schema).map(methodFromRequirement)).toEqual([
            expect.objectContaining({ method_kind: 'api_key', is_oauth: false }),
        ]);
        const operations = getAgentToolOperations('automation-me-qr-qr-code').map(op => op.operation);
        expect(operations).toHaveLength(21);
        expect(operations).toEqual(expect.arrayContaining(['list_folders', 'create_link_qr', 'update_email_qr', 'delete_entries', 'get_analytics']));
    });
});
