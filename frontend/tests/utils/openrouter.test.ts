import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';
const schema = JSON.parse(readFileSync(join(__dirname, '../../app/schemas/nodes/openrouter.json'), 'utf8'));
describe('OpenRouter connect method', () => {
  it('offers a pasted API key with management-key requirements', () => {
    const methods = requirementsFromSchema(schema).map(methodFromRequirement);
    expect(methods).toHaveLength(1);
    expect(methods[0]).toMatchObject({ credential_type: 'openrouter_api_key', method_kind: 'api_key', is_oauth: false });
    const credential = schema.$defs.OpenRouterAPIKey;
    expect(credential.title).toBe('OpenRouter API Key');
    expect(credential.properties.api_key['ui:widget']).toBe('password');
    expect(credential['x-credential-url']).toBe('https://openrouter.ai/settings/keys');
    expect(credential['x-credential-instructions']).toContain('management key');
  });
});
