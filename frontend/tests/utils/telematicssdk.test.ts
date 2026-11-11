import { beforeAll, describe, expect, it } from 'vitest';
import { TelematicsSDKNode } from '~/components/workflow/nodes/integrations/telematicssdk';
import { NODE_SCHEMAS, loadNodeSchemas, getAgentToolOperations, getNodeCredentialInfo } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
const type = 'automation-telematicssdk';
describe('Telematics SDK', () => {
    beforeAll(() => loadNodeSchemas([type]));
    it('offers a pasted token connection and industry placement', () => {
        expect(TelematicsSDKNode.category).toBe('industry');
        expect(getNodeCredentialInfo(type)?.acceptedTypes).toEqual(['telematicssdk_token']);
        expect(requirementsFromSchema(NODE_SCHEMAS[type]).map(methodFromRequirement)).toEqual([
            expect.objectContaining({ method_kind: 'api_key', is_oauth: false }),
        ]);
    });
    it('exposes 13 actions separately from its new-user trigger', () => {
        expect(getAgentToolOperations(type)).toHaveLength(13);
    });
});
