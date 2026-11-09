import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';

const schema = JSON.parse(readFileSync(join(__dirname, '../../app/schemas/nodes/amplemarket.json'), 'utf8'));
describe('Amplemarket credentials', () => {
    it('supports manually pasting an API key and names the account verification read', () => {
        const methods = requirementsFromSchema(schema).map(methodFromRequirement);
        expect(methods).toHaveLength(1);
        expect(methods[0]).toMatchObject({ credential_type: 'amplemarket_api_key', method_kind: 'api_key', is_oauth: false });
        const credential = schema.$defs.AmplemarketAPIKeyCredential;
        expect(credential.title).toBe('Amplemarket API Key');
        expect(credential.properties.credential_type.default).toBe('amplemarket_api_key');
        expect(credential.properties.api_key['ui:widget']).toBe('password');
        expect(credential['x-credential-instructions']).toContain('Settings > API');
        expect(credential['x-credential-instructions']).toContain('account details');
    });
});
