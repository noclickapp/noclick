import { beforeAll, expect, it } from 'vitest';
import { FungeneratorsNode } from '~/components/workflow/nodes/integrations/fungenerators';
import { getNodeCredentialInfo, NODE_SCHEMAS, loadNodeSchemas, getAgentToolOperations } from '~/utils/nodeSchemas';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';

const type = 'automation-fungenerators';
beforeAll(() => loadNodeSchemas([type]));
it('discovers UUID Generation API with one manual API key method', () => {
    expect(FungeneratorsNode.type).toBe(type);
    expect(FungeneratorsNode.category).toBe('developer-tools');
    expect(getNodeCredentialInfo(type)?.acceptedTypes).toEqual(['fungenerators_api_key']);
    const requirements = requirementsFromSchema(NODE_SCHEMAS[type]);
    expect(requirements).toHaveLength(1);
    expect(methodFromRequirement(requirements[0])).toMatchObject({ method_kind: 'api_key', is_oauth: false });
    expect(getAgentToolOperations(type)).toHaveLength(2);
});
