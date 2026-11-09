import { beforeAll, expect, it } from 'vitest';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { SimplicateNode } from '~/components/workflow/nodes/integrations/simplicate';

beforeAll(async () => { await loadNodeSchemas(['automation-simplicate']); });
it('discovers Simplicate, manual API credentials and read/write operations', () => {
    expect(SimplicateNode.category).toBe('crm-sales');
    expect(getNodeCredentialInfo(SimplicateNode.type)?.acceptedTypes).toEqual(['simplicate_api_key']);
    expect(credentialRequirements(SimplicateNode.type).map(methodFromRequirement)).toEqual([
        expect.objectContaining({ credential_type: 'simplicate_api_key', method_kind: 'api_key', is_oauth: false }),
    ]);
    const operations = getAgentToolOperations(SimplicateNode.type).map(op => op.operation);
    expect(operations).toHaveLength(23);
    expect(operations).toEqual(expect.arrayContaining(['get_project', 'list_relation_types', 'create_relation_type', 'create_sale_service_group']));
});
