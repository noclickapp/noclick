// Check the generated OpenWA credential against the shared connection form.
// This keeps the server origin and pasted API key usable without an OAuth flow.
import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '../../app/schemas/nodes/openwa.json';

describe('OpenWA manual connection', () => {
    it('offers a server origin and API key with a default credential type', () => {
        const method = methodFromRequirement(requirementsFromSchema(schema)[0]);
        expect(method.method_kind).toBe('api_key');
        expect(method.is_oauth).toBe(false);
        const credential = schema.$defs.OpenWAAPIKeyCredential;
        expect(credential.required).toEqual(['server_url', 'api_key']);
        expect(credential.properties.credential_type.default).toBe('openwa_api_key');
        expect(credential.properties.api_key['ui:widget']).toBe('password');
    });
});
