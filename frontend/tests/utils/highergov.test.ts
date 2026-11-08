// HigherGov metadata must discover all provider reads and the manual key method.
// This checks the generated schema through the same lazy loading as the UI.
import { beforeAll, describe, expect, it } from 'vitest';
import { HigherGovNode } from '~/components/workflow/nodes/integrations/highergov';
import { getAgentToolOperations, getNodeCredentialInfo, loadNodeSchemas, NODE_SCHEMAS } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';

const type = 'automation-highergov';
beforeAll(() => loadNodeSchemas([type]));

describe('HigherGov integration', () => {
    it('discovers the native definition, key credential and all nineteen reads', () => {
        expect(HigherGovNode.type).toBe(type);
        expect(getNodeCredentialInfo(type)?.acceptedTypes).toEqual(['highergov_api_key']);
        expect(getAgentToolOperations(type)).toHaveLength(19);
    });

    it('offers a pasted API key connection', () => {
        const requirements = requirementsFromSchema(NODE_SCHEMAS[type]);
        expect(requirements).toHaveLength(1);
        expect(methodFromRequirement(requirements[0])).toMatchObject({ method_kind: 'api_key', is_oauth: false });
    });
});
