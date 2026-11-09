import { beforeAll, describe, expect, it } from 'vitest';
import { V0Node } from '~/components/workflow/nodes/integrations/v0';
import { loadNodeSchemas, NODE_SCHEMAS } from '~/utils/nodeSchemas';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';

describe('V0 integration discovery', () => {
    beforeAll(() => loadNodeSchemas(['automation-v0']));
    it('publishes its AI catalog entry and a manually connectable API key', () => {
        expect(V0Node.type).toBe('automation-v0');
        expect(V0Node.category).toBe('ai');
        expect(CREDENTIAL_TYPE_MAP.V0APIKeyCredential).toBe('v0_api_key');
        const requirements = requirementsFromSchema(NODE_SCHEMAS['automation-v0']);
        expect(requirements).toHaveLength(1);
        const method = methodFromRequirement(requirements[0]);
        expect(method.credential_fields?.map(field => field.name)).toContain('api_key');
    });
});
