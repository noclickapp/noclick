import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '../../app/schemas/nodes/sakari-sms.json';

describe('Sakari SMS manual API client connection', () => {
    it('offers the three typed credential fields without an OAuth sign-in', () => {
        const method = methodFromRequirement(requirementsFromSchema(schema)[0]);
        expect(method.method_kind).toBe('api_key');
        expect(method.is_oauth).toBe(false);
        const credential = schema.$defs.SakariSMSAPICredential;
        expect(credential.required).toEqual(['account_id', 'client_id', 'client_secret']);
        expect(credential.properties.credential_type.default).toBe('sakari_sms_api_credentials');
        expect(credential.properties.client_secret['ui:widget']).toBe('password');
    });
});
