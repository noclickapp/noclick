import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';
const schema = JSON.parse(readFileSync(join(__dirname, '../../app/schemas/nodes/inforumobile.json'), 'utf8'));
describe('InforUMobile manual connection', () => {
  it('offers a username and pasted API token', () => {
    const methods = requirementsFromSchema(schema).map(methodFromRequirement);
    expect(methods).toHaveLength(1);
    expect(methods[0]).toMatchObject({ credential_type: 'inforumobile_api_token', method_kind: 'api_key', is_oauth: false });
    const credential = schema.$defs.InforUMobileCredential;
    expect(credential.title).toBe('InforUMobile API Token');
    expect(credential.properties.credential_type.default).toBe('inforumobile_api_token');
    expect(credential.properties.api_token['ui:widget']).toBe('password');
    expect(credential.required).toEqual(['username', 'api_token']);
  });
});
