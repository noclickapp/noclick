// Check Payaca's generated credential schema through the shared connect consumers.
// Pasted client credentials must expose both fields and use the manual key method.
import { expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';

const schema = JSON.parse(readFileSync(join(__dirname, '../../app/schemas/nodes/payaca.json'), 'utf8'));

it('offers Payaca client credentials for manual connection', () => {
    const methods = requirementsFromSchema(schema).map(methodFromRequirement);
    expect(methods).toHaveLength(1);
    expect(methods[0]).toMatchObject({ credential_type: 'payaca_api_key', method_kind: 'api_key', is_oauth: false });
    const credential = schema.$defs.PayacaAPIKeyCredential;
    expect(credential.properties.credential_type.default).toBe('payaca_api_key');
    expect(credential.required).toEqual(['client_id', 'client_secret']);
    expect(credential.properties.client_secret['ui:widget']).toBe('password');
    expect(credential['x-credential-instructions']).toContain('Create API key');
});
