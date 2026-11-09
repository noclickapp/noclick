import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
const schema = JSON.parse(readFileSync(join(__dirname, '../../app/schemas/nodes/google-ai-studio.json'), 'utf8'));
describe('Google AI Studio credentials', () => {
  it('offers a pasted API key with the correct method kind and label', () => {
    expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
    expect(getCredentialTypeFromSchemaTitle('Google AI Studio API Key')).toBe('google_ai_studio_api_key');
  });
});
