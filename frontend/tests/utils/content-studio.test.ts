// Checks Content Studio's generated credential form through shared consumers.
// Pins its pasted API key method, secret widget and connection instructions.
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';

const schema = JSON.parse(readFileSync(join(__dirname, '../../app/schemas/nodes/content-studio.json'), 'utf8'));
describe('Content Studio connect method', () => {
    it('offers a pasted API key with instructions and account evidence', () => {
        const methods = requirementsFromSchema(schema).map(methodFromRequirement);
        expect(methods).toHaveLength(1);
        expect(methods[0]).toMatchObject({ credential_type: 'content_studio_api_key', method_kind: 'api_key', is_oauth: false });
        const credential = schema.$defs.ContentStudioAPIKeyCredential;
        expect(credential.title).toBe('Content Studio API Key');
        expect(credential.properties.api_key['ui:widget']).toBe('password');
        expect(credential['x-credential-url']).toBe('https://docs.contentstudio.io/articles/contentstudio-api-f955a6ab');
        expect(credential['x-credential-instructions']).toContain('X-API-Key');
        expect(credential['x-credential-instructions']).toContain('workspaces');
    });
});
