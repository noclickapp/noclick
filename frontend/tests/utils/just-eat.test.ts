// Check that Just Eat's generated credential works with the shared manual-connect form.
// This keeps its pasted delivery token from being mistaken for an OAuth sign-in.
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';

const schema = JSON.parse(readFileSync(join(__dirname, '../../app/schemas/nodes/just-eat.json'), 'utf8'));

describe('Just Eat UK manual connection', () => {
    it('offers one pasted delivery token with clear expiration instructions', () => {
        const methods = requirementsFromSchema(schema).map(methodFromRequirement);
        expect(methods).toHaveLength(1);
        expect(methods[0]).toMatchObject({ credential_type: 'just_eat_token', method_kind: 'api_key', is_oauth: false });
        const credential = schema.$defs.JustEatTokenCredential;
        expect(credential.properties.access_token['ui:widget']).toBe('password');
        expect(credential.properties.credential_type.default).toBe('just_eat_token');
        expect(credential['x-credential-instructions']).toContain('Tokens expire');
    });
});
