import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { NODE_SCHEMA_TYPES } from '~/utils/nodeMeta';
import schema from '~/schemas/nodes/tidio.json';

// The generated schema drives every manual connect surface.
describe('Tidio credentials', () => {
    it('offers a pasted API key with both required fields and no OAuth sign-in', () => {
        expect(NODE_SCHEMA_TYPES).toContain('automation-tidio');
        const requirements = requirementsFromSchema(schema);
        expect(requirements).toHaveLength(1);
        expect(methodFromRequirement(requirements[0])).toMatchObject({
            credential_type: 'tidio_api_key', method_kind: 'api_key', is_oauth: false,
        });
        const credential = schema.$defs.TidioAPIKeyCredential;
        expect(credential.required).toEqual(['client_id', 'client_secret']);
        expect(credential.properties.credential_type.default).toBe('tidio_api_key');
    });
});
