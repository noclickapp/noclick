import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';
const schema = JSON.parse(readFileSync(join(__dirname, '../../app/schemas/nodes/transloadit.json'), 'utf8'));
describe('Transloadit manual connection', () => {
    it('offers a pasted token with expiry and scope instructions', () => {
        const methods = requirementsFromSchema(schema).map(methodFromRequirement);
        expect(methods).toHaveLength(1);
        expect(methods[0]).toMatchObject({ credential_type: 'transloadit_token', method_kind: 'api_key', is_oauth: false });
        const credential = schema.$defs.TransloaditTokenCredential;
        expect(credential.title).toBe('Transloadit Bearer Token');
        expect(credential.properties.access_token['ui:widget']).toBe('password');
        expect(credential['x-credential-url']).toBe('https://transloadit.com/docs/api/token-post/');
        expect(credential['x-credential-instructions']).toContain('six hours');
        expect(credential['x-credential-instructions']).toContain('templates:read');
    });
});
