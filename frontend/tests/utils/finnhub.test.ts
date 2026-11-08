import { beforeAll, expect, it } from 'vitest';
import { FinnhubNode } from '~/components/workflow/nodes/integrations/finnhub';
import { NODE_SCHEMAS, loadNodeSchemas, getAgentToolOperations, getNodeCredentialInfo } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';

const type = 'automation-finnhub';
beforeAll(() => loadNodeSchemas([type]));
it('discovers Finnhub with a manual API key and twenty operations', () => {
    expect(FinnhubNode.category).toBe('finance-accounting');
    expect(getNodeCredentialInfo(type)?.acceptedTypes).toEqual(['finnhub_api_key']);
    expect(requirementsFromSchema(NODE_SCHEMAS[type]).map(methodFromRequirement)).toEqual([
        expect.objectContaining({ method_kind: 'api_key', is_oauth: false }),
    ]);
    expect(getAgentToolOperations(type)).toHaveLength(20);
});
