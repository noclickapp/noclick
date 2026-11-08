import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';
const schema = JSON.parse(readFileSync(join(__dirname, '../../app/schemas/nodes/seam.json'), 'utf8'));
describe('Seam connect method', () => {
  it('offers a pasted workspace API key and console setup link', () => {
    const methods = requirementsFromSchema(schema).map(methodFromRequirement);
    expect(methods).toHaveLength(1);
    expect(methods[0]).toMatchObject({ credential_type: 'seam_api_key', method_kind: 'api_key', is_oauth: false });
    const credential = schema.$defs.SeamAPIKeyCredential;
    expect(credential.title).toBe('Seam API Key');
    expect(credential.properties.api_key['ui:widget']).toBe('password');
    expect(credential['x-credential-url']).toBe('https://console.seam.co/');
    expect(credential['x-credential-instructions']).toContain('sandbox');
  });
});
