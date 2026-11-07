import { beforeAll, describe, expect, it } from 'vitest';
import schema from '~/schemas/nodes/coveo.json';
import { CoveoNode } from '~/components/workflow/nodes/integrations/coveo';
import { getAgentToolOperations, getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
const type = 'automation-coveo';
beforeAll(() => loadNodeSchemas([type]));
describe('Coveo integration', () => {
    it('discovers the native definition, credential and sixteen operations', () => {
        expect(CoveoNode.type).toBe(type);
        expect(getNodeCredentialInfo(type)?.acceptedTypes).toEqual(['coveo_api_key']);
        expect(getAgentToolOperations(type)).toHaveLength(16);
    });
    it('offers an API key method without OAuth', () => {
        const requirements = requirementsFromSchema(schema);
        expect(requirements).toHaveLength(1);
        const method = methodFromRequirement(requirements[0]);
        expect(method.method_kind).toBe('api_key');
        expect(method.is_oauth).toBe(false);
    });
});
