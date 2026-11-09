import { describe, expect, it } from 'vitest';
import { loadNodeSchemas, NODE_SCHEMAS } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';

describe('Quentn manual connect', () => {
    it('offers API key authentication and both required fields', async () => {
        await loadNodeSchemas(['automation-quentn']);
        const requirements = requirementsFromSchema(NODE_SCHEMAS['automation-quentn']);
        expect(requirements).toHaveLength(1);
        const method = methodFromRequirement(requirements[0]);
        expect(method).toMatchObject({ credential_type: 'quentn_api_key', method_kind: 'api_key', is_oauth: false });
        expect(method.credential_fields?.filter(field => field.required).map(field => field.name).sort()).toEqual(['api_base_url', 'api_key']);
    });
});
