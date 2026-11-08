import { beforeAll, describe, expect, it } from 'vitest';
import { AvomaNode } from '~/components/workflow/nodes/integrations/avoma';
import {
    NODE_SCHEMAS,
    loadNodeSchemas,
    getAgentToolOperations,
    getNodeCredentialInfo,
} from '~/utils/nodeSchemas';
import {
    methodFromRequirement,
    requirementsFromSchema,
} from '~/components/credential/credentialMethods';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';

const type = 'automation-avoma';
describe('Avoma integration', () => {
    beforeAll(() => loadNodeSchemas([type]));
    it('discovers the definition, pasted API key method and operation catalog', () => {
        const schema = NODE_SCHEMAS[type];
        expect(AvomaNode.type).toBe(type);
        expect(CREDENTIAL_TYPE_MAP.AvomaAPIKey).toBe('avoma_api_key');
        expect(getNodeCredentialInfo(type)?.acceptedTypes).toEqual([
            'avoma_api_key',
        ]);
        expect(
            methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind
        ).toBe('api_key');
        expect(getAgentToolOperations(type)).toHaveLength(23);
    });
});
