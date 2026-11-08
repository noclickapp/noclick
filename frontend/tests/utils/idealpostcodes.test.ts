import { expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';
const schema = JSON.parse(readFileSync(join(__dirname, '../../app/schemas/nodes/idealpostcodes.json'), 'utf8'));
it('Ideal Postcodes connects with a pasted API key and optional management key', () => {
    const methods = requirementsFromSchema(schema).map(methodFromRequirement);
    expect(methods).toHaveLength(1);
    expect(methods[0]).toMatchObject({ credential_type: 'idealpostcodes_api_key', method_kind: 'api_key', is_oauth: false });
    const credential = schema.$defs.IdealpostcodesAPIKeyCredential;
    expect(credential.properties.credential_type.default).toBe('idealpostcodes_api_key');
    expect(credential.required).toEqual(['api_key']);
    expect(credential.properties.api_key['ui:widget']).toBe('password');
    expect(credential.properties.user_token['ui:widget']).toBe('password');
});
