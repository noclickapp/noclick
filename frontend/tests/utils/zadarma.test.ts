// Exercise Zadarma discovery and its manual API-key connection method.
// The public catalog and canvas share this definition and generated metadata.
import { beforeAll, describe, expect, it } from 'vitest';
import { ZadarmaNode } from '~/components/workflow/nodes/integrations/zadarma';
import { getAgentToolOperations, getNodeCredentialInfo, loadNodeSchemas, NODE_SCHEMAS } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
const type = 'automation-zadarma';
beforeAll(() => loadNodeSchemas([type]));
describe('Zadarma integration', () => {
    it('discovers twenty operations and a communication definition', () => {
        expect(ZadarmaNode.type).toBe(type);
        expect(ZadarmaNode.category).toBe('communication');
        expect(getNodeCredentialInfo(type)?.acceptedTypes).toEqual(['zadarma_api_key']);
        expect(getAgentToolOperations(type)).toHaveLength(20);
    });
    it('offers the API key and secret as a manual method', () => {
        const requirements = requirementsFromSchema(NODE_SCHEMAS[type]);
        expect(requirements).toHaveLength(1);
        const method = methodFromRequirement(requirements[0]);
        expect(method.method_kind).toBe('api_key');
        expect(method.is_oauth).toBe(false);
        expect(method.credential_fields?.map(field => field.name).sort()).toEqual(['api_key', 'api_secret']);
    });
});
