import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';
const schema = JSON.parse(readFileSync(join(__dirname, '../../app/schemas/nodes/databox.json'), 'utf8'));
describe('Databox connect method', () => {
  it('offers a pasted API key with profile verification', () => {
    const methods = requirementsFromSchema(schema).map(methodFromRequirement);
    expect(methods).toHaveLength(1);
    expect(methods[0]).toMatchObject({ credential_type: 'databox_api_key', method_kind: 'api_key', is_oauth: false });
    const credential = schema.$defs.DataboxAPIKey;
    expect(credential.title).toBe('Databox API Key');
    expect(credential.properties.api_key['ui:widget']).toBe('password');
    expect(credential['x-credential-url']).toBe('https://developers.databox.com/docs/api/authentication');
    expect(credential['x-credential-instructions']).toContain('profile');
  });
});
