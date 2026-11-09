// Synap's generated credential metadata must support manual connection.
// This checks the public connect method and both person-supplied fields.
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';

const schema = JSON.parse(readFileSync(new URL('../../app/schemas/nodes/synap.json', import.meta.url), 'utf8'));
describe('Synap connect', () => {
    it('offers a token and portal ID as a manual API key method', () => {
        const [requirement] = requirementsFromSchema(schema);
        const method = methodFromRequirement(requirement);
        expect(method).toMatchObject({ credential_type: 'synap_pat', method_kind: 'api_key', is_oauth: false });
        expect(method.credential_fields?.map(field => field.name)).toEqual(['api_token', 'portal_id']);
        expect(method.credential_fields?.every(field => field.required)).toBe(true);
    });
});
