import { beforeAll, describe, expect, it } from 'vitest';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { GetAcceptNode } from '~/components/workflow/nodes/integrations/getaccept';

describe('GetAccept integration', () => {
    beforeAll(() => loadNodeSchemas(['automation-getaccept']));

    it('discovers the brand, category and manually connected access token', async () => {
        const { default: schema } = await import('~/schemas/nodes/getaccept.json');
        expect(GetAcceptNode.type).toBe('automation-getaccept');
        expect(GetAcceptNode.label).toBe('GetAccept');
        expect(GetAcceptNode.category).toBe('crm-sales');
        expect(getNodeCredentialInfo('automation-getaccept')?.acceptedTypes).toEqual(['getaccept_access_token']);
        expect(getCredentialTypeFromSchemaTitle('GetAccept Access Token')).toBe('getaccept_access_token');
        expect(requirementsFromSchema(schema).map(methodFromRequirement)).toEqual([
            expect.objectContaining({ method_kind: 'api_key', is_oauth: false }),
        ]);
    });

    it('exposes the fixed document and contact operations', () => {
        const operations = getAgentToolOperations('automation-getaccept').map(op => op.operation);
        expect(operations).toHaveLength(21);
        expect(operations).toEqual(expect.arrayContaining([
            'list_documents', 'create_document', 'update_document', 'send_document', 'send_reminder',
            'create_contact', 'delete_contact', 'list_templates', 'test_authentication',
        ]));
    });
});
