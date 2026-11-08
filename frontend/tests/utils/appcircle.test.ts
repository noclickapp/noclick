// Appcircle must expose a typed-in access-token connection in every connect surface.
// This checks the generated schema and method classification used by those forms.
import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { CREDENTIAL_TYPE_MAP } from '../../app/utils/credentialTypeMap';
import schema from '../../app/schemas/nodes/appcircle.json';

describe('Appcircle credentials', () => {
    it('offers one manual access-token method with a hidden discriminator', () => {
        const requirements = requirementsFromSchema(schema);
        expect(requirements).toHaveLength(1);
        expect(methodFromRequirement(requirements[0]).method_kind).toBe('api_key');
        expect(CREDENTIAL_TYPE_MAP.AppcircleAccessTokenCredential).toBe('appcircle_access_token');
        const credential = schema.$defs.AppcircleAccessTokenCredential;
        expect(credential.title).toBe('Appcircle Access Token');
        expect(credential.required).toEqual(['access_token']);
        expect(credential.properties.credential_type.default).toBe('appcircle_access_token');
        expect(credential.properties.access_token['ui:widget']).toBe('password');
        expect(credential['x-credential-instructions']).toContain('expire');
    });
});
