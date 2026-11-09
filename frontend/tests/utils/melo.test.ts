import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';
const schema = JSON.parse(readFileSync(join(__dirname, '../../app/schemas/nodes/melo.json'), 'utf8'));
describe('Melo manual connect method', () => {
    it('offers a pasted API key and the official console instructions', () => {
        const methods = requirementsFromSchema(schema).map(methodFromRequirement);
        expect(methods).toHaveLength(1);
        expect(methods[0]).toMatchObject({ credential_type: 'melo_api_key', method_kind: 'api_key', is_oauth: false });
        const credential = schema.$defs.MeloAPIKeyCredential;
        expect(credential.properties.credential_type.default).toBe('melo_api_key');
        expect(credential.properties.api_key['ui:widget']).toBe('password');
        expect(credential['x-credential-url']).toBe('https://stream.estate/console');
        expect(credential['x-credential-instructions']).toContain('saved searches');
    });
});
