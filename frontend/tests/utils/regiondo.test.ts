import { describe, expect, it } from 'vitest';
import { loadNodeSchemas, NODE_SCHEMAS } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';

describe('Regiondo manual connect', () => {
    it('offers the HMAC key pair as two editable required fields', async () => {
        await loadNodeSchemas(['automation-regiondo']);
        const requirements = requirementsFromSchema(NODE_SCHEMAS['automation-regiondo']);
        expect(requirements).toHaveLength(1);
        const method = methodFromRequirement(requirements[0]);
        expect(method).toMatchObject({ credential_type: 'regiondo_api_key', method_kind: 'api_key', is_oauth: false });
        expect(method.credential_fields?.filter(field => field.required).map(field => field.name).sort()).toEqual(['private_key', 'public_key']);
    });
});
