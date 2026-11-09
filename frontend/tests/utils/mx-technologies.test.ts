import { beforeAll, describe, expect, it } from 'vitest';
import { MxTechnologiesNode } from '~/components/workflow/nodes/integrations/mx-technologies';
import { NODE_SCHEMAS, loadNodeSchemas, getAgentToolOperations, getNodeCredentialInfo } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';

const type = 'automation-mx-technologies';
describe('MX Technologies', () => {
    beforeAll(() => loadNodeSchemas([type]));
    it('discovers the definition and a pasted API key connection', () => {
        expect(MxTechnologiesNode.type).toBe(type);
        expect(MxTechnologiesNode.label).toBe('MX Technologies');
        expect(getNodeCredentialInfo(type)?.acceptedTypes).toEqual(['mx_technologies_api_key']);
        const methods = requirementsFromSchema(NODE_SCHEMAS[type]).map(methodFromRequirement);
        expect(methods).toHaveLength(1);
        expect(methods[0]).toMatchObject({ method_kind: 'api_key', is_oauth: false });
    });
    it('exposes user, member, account and transaction operations', () => {
        expect(getAgentToolOperations(type)).toHaveLength(19);
    });
});
