// Checks the generated Whop credential form through the shared UI consumers.
// Pins the pasted-key method and setup instructions for the new integration.
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';
const schema = JSON.parse(readFileSync(join(__dirname, '../../app/schemas/nodes/whop.json'), 'utf8'));
describe('Whop connect method', () => {
  it('offers the production account API key with a password field and setup link', () => {
    const methods = requirementsFromSchema(schema).map(methodFromRequirement);
    expect(methods).toHaveLength(1);
    expect(methods[0]).toMatchObject({ credential_type: 'whop_api_key', method_kind: 'api_key', is_oauth: false });
    const credential = schema.$defs.WhopAPIKeyCredential;
    expect(credential.title).toBe('Whop API Key');
    expect(credential.properties.api_key['ui:widget']).toBe('password');
    expect(credential['x-credential-url']).toBe('https://whop.com/dashboard/developer');
    expect(credential['x-credential-instructions']).toContain('company:balance:read');
  });
});
