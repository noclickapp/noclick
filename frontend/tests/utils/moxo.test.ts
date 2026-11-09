import { beforeAll, expect, it } from 'vitest';
import { MoxoNode } from '~/components/workflow/nodes/integrations/moxo';
import { NODE_SCHEMAS, loadNodeSchemas, getAgentToolOperations, getNodeCredentialInfo } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';

const type = 'automation-moxo';
beforeAll(() => loadNodeSchemas([type]));
it('discovers Moxo with a manual personal token and twenty operations', () => {
    expect(MoxoNode.category).toBe('productivity');
    expect(getNodeCredentialInfo(type)?.acceptedTypes).toEqual(['moxo_api_token']);
    expect(requirementsFromSchema(NODE_SCHEMAS[type]).map(methodFromRequirement)).toEqual([
        expect.objectContaining({ method_kind: 'api_key', is_oauth: false }),
    ]);
    expect(getAgentToolOperations(type)).toHaveLength(20);
});
