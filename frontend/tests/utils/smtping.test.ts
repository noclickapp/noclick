// Verifies the generated Smtping credential can be connected by hand.
// Guards the visible API-key field, default type and connection method metadata.
import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/smtping.json';
import meta from '~/schemas/nodeMeta/smtping.json';

// The public connect catalog must be able to shape this by hand.
describe('Smtping manual connection', () => {
    it('offers one API key method and requires only the visible secret', () => {
        const requirements = requirementsFromSchema(schema);
        expect(requirements.map(req => req.credential_type)).toEqual(['smtping_api_key']);
        expect(methodFromRequirement(requirements[0]).method_kind).toBe('api_key');
        expect(meta.credentialTypes.SmtpingApiKeyCredential).toBe('smtping_api_key');
        expect(schema.$defs.SmtpingApiKeyCredential.required).toEqual(['api_key']);
        expect(schema.$defs.SmtpingApiKeyCredential.properties.credential_type.default).toBe('smtping_api_key');
        expect(schema.$defs.SmtpingApiKeyCredential.properties.api_key['ui:widget']).toBe('password');
    });
});
