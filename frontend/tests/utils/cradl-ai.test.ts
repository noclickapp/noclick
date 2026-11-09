// Verifies Cradl AI's generated credential form through the shared connect UI.
// The single pasted token must remain manually connectable with clear expiry guidance.
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';
const schema = JSON.parse(readFileSync(join(__dirname, '../../app/schemas/nodes/cradl-ai.json'), 'utf8'));

describe('Cradl AI manual connect', () => {
    it('offers one pasted access token with expiry guidance', () => {
        const requirements = requirementsFromSchema(schema);
        expect(requirements).toHaveLength(1);
        const method = methodFromRequirement(requirements[0]);
        expect(method).toMatchObject({ credential_type: 'cradl_ai_access_token', method_kind: 'api_key', is_oauth: false });
        expect(method.credential_fields).toEqual([expect.objectContaining({ name: 'access_token', required: true, type: 'password' })]);
        expect(method.instructions).toContain('Tokens expire');
        expect(method.credential_url).toBe('https://docs.cradl.ai/api-reference/introduction');
        expect(schema.$defs.CradlAIAccessTokenCredential.properties.credential_type.default).toBe('cradl_ai_access_token');
    });
});
