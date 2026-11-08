// Keep Bluefox Email's discovered catalog and manual connection usable.
// This checks the generated schema through the same loaders the product uses.
import { beforeAll, describe, expect, it } from 'vitest';
import { loadNodeSchemas, NODE_SCHEMAS, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { BluefoxEmailNode } from '~/components/workflow/nodes/integrations/bluefox-email';

describe('Bluefox Email', () => {
    beforeAll(() => loadNodeSchemas(['automation-bluefox-email']));
    it('offers a marketing integration with a manual project API key', () => {
        expect(BluefoxEmailNode.category).toBe('marketing');
        const method = methodFromRequirement(requirementsFromSchema(NODE_SCHEMAS[BluefoxEmailNode.type])[0]);
        expect(method).toMatchObject({ method_kind: 'api_key', is_oauth: false });
        expect(getNodeCredentialInfo(BluefoxEmailNode.type)?.acceptedTypes).toEqual(['bluefox_email_api_key']);
        expect(method.credential_fields?.filter(field => field.required).map(field => field.name).sort()).toEqual(['api_key', 'project_id']);
        expect(getAgentToolOperations(BluefoxEmailNode.type)).toHaveLength(24);
    });
});
