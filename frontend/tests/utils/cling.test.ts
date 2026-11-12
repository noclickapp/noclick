// Checks that Cling is discoverable with its manual API key connection.
// Keeps the public category and action catalog aligned with generated metadata.
import { beforeAll, expect, it } from 'vitest';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { ClingNode } from '~/components/workflow/nodes/integrations/cling';

beforeAll(async () => { await loadNodeSchemas(['automation-cling']); });
it('discovers the documents integration and its pasted API key method', () => {
    expect(ClingNode.category).toBe('documents');
    expect(getNodeCredentialInfo(ClingNode.type)?.acceptedTypes).toEqual(['cling_api_key']);
    expect(credentialRequirements(ClingNode.type).map(methodFromRequirement)).toEqual([
        expect.objectContaining({ credential_type: 'cling_api_key', method_kind: 'api_key', is_oauth: false }),
    ]);
    const operations = getAgentToolOperations(ClingNode.type).map(op => op.operation);
    expect(operations).toHaveLength(21);
    expect(operations).toEqual(expect.arrayContaining(['list_documents', 'create_document', 'send_document', 'create_customer', 'update_project']));
    expect(operations).not.toContain('on_document_accepted');
});
