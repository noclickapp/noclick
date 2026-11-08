import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/icypeas.json';
import meta from '~/schemas/nodeMeta/icypeas.json';

describe('Icypeas manual connection', () => {
    it('offers one API key method with a default credential type and visible account email', () => {
        const requirements = requirementsFromSchema(schema);
        expect(requirements.map(req => req.credential_type)).toEqual(['icypeas_api_key']);
        expect(methodFromRequirement(requirements[0]).method_kind).toBe('api_key');
        expect(meta.credentialTypes.IcypeasAPIKeyCredential).toBe('icypeas_api_key');
        expect(schema.$defs.IcypeasAPIKeyCredential.required).toEqual(['api_key', 'email']);
        expect(schema.$defs.IcypeasAPIKeyCredential.properties.credential_type.default).toBe('icypeas_api_key');
    });
});
