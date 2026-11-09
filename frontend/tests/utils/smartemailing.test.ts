// Verify SmartEmailing is discoverable and its required fields can be entered by hand.
// This exercises generated metadata through the product's schema loader.
import { beforeAll, describe, expect, it } from 'vitest';
import { loadNodeSchemas, NODE_SCHEMAS, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { SmartEmailingNode } from '~/components/workflow/nodes/integrations/smartemailing';

describe('SmartEmailing', () => {
    beforeAll(() => loadNodeSchemas(['automation-smartemailing']));
    it('offers a marketing integration with manually entered username and API key', () => {
        expect(SmartEmailingNode.category).toBe('marketing');
        const method = methodFromRequirement(requirementsFromSchema(NODE_SCHEMAS[SmartEmailingNode.type])[0]);
        expect(method).toMatchObject({ method_kind: 'api_key', is_oauth: false });
        expect(getNodeCredentialInfo(SmartEmailingNode.type)?.acceptedTypes).toEqual(['smartemailing_api_key']);
        expect(method.credential_fields?.filter(field => field.required).map(field => field.name).sort()).toEqual(['api_key', 'username']);
        expect(getAgentToolOperations(SmartEmailingNode.type)).toHaveLength(23);
    });
});
