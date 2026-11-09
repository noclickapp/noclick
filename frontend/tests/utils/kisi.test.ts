import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { CREDENTIAL_TYPE_MAP } from '../../app/utils/credentialTypeMap';
import schema from '../../app/schemas/nodes/kisi.json';

describe('Kisi manual connection', () => {
    it('offers one API key method whose only required field can be pasted', () => {
        const requirements = requirementsFromSchema(schema);
        expect(requirements).toHaveLength(1);
        expect(methodFromRequirement(requirements[0]).method_kind).toBe('api_key');
        expect(CREDENTIAL_TYPE_MAP.KisiAPIKeyCredential).toBe('kisi_api_key');
        const credential = schema.$defs.KisiAPIKeyCredential;
        expect(credential.title).toBe('Kisi API Key');
        expect(credential.required).toEqual(['api_key']);
        expect(credential.properties.credential_type.default).toBe('kisi_api_key');
        expect(credential.properties.api_key['ui:widget']).toBe('password');
        expect(credential['x-credential-instructions']).toContain('KISI-LOGIN');
    });
});
