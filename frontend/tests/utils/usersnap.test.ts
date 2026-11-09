// Verifies the generated Usersnap connect form offers the documented manual token.
// This protects hand connecting and keeps token authentication out of OAuth flows.
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';
const schema = JSON.parse(readFileSync(join(__dirname, '../../app/schemas/nodes/usersnap.json'), 'utf8'));

describe('Usersnap manual connect', () => {
    it('offers one pasted JWT with Enterprise and signing guidance', () => {
        const requirements = requirementsFromSchema(schema);
        expect(requirements).toHaveLength(1);
        const method = methodFromRequirement(requirements[0]);
        expect(method).toMatchObject({ credential_type: 'usersnap_api_token', method_kind: 'api_key', is_oauth: false });
        expect(method.credential_fields).toEqual([expect.objectContaining({ name: 'api_token', required: true, type: 'password' })]);
        expect(method.instructions).toContain('Enterprise');
        expect(method.instructions).toContain('HS256');
        expect(schema.$defs.UsersnapTokenCredential.properties.credential_type.default).toBe('usersnap_api_token');
    });
});
