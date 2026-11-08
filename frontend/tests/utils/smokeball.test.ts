import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';
const schema = JSON.parse(readFileSync(join(__dirname, '../../app/schemas/nodes/smokeball.json'), 'utf8'));
describe('Smokeball connection', () => {
  it('offers the declared user OAuth provider with resource scopes', () => {
    const methods = requirementsFromSchema(schema).map(methodFromRequirement);
    expect(methods).toHaveLength(1);
    expect(methods[0]).toMatchObject({ credential_type: 'smokeball_oauth', method_kind: 'oauth', is_oauth: true, oauth_provider: 'smokeball' });
    const credential = schema.$defs.SmokeballOAuthCredential;
    expect(credential.title).toBe('Smokeball Account');
    expect(credential['x-oauth-scopes']).toContain('firm/read');
    expect(credential['x-oauth-scopes']).toContain('tasks/write');
    expect(credential['x-credential-instructions']).toContain('US Smokeball account');
    expect(credential['x-credential-url']).toBe('https://console.smokeball.com');
  });
});
