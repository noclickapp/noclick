import { describe, expect, it } from 'vitest';
import schema from '../../app/schemas/nodes/omnisend.json';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';

// Keep both authentication methods visible in the existing connect dialog.
// A nested discriminated credential union is valid JSON Schema but is not
// the direct anyOf reference shape the dialog consumes.
describe('Omnisend connections', () => {
    it('offers the declared OAuth provider and API key', () => {
        const methods = requirementsFromSchema(schema).map(methodFromRequirement);
        expect(methods.map(method => method.credential_type)).toEqual([
            'omnisend_oauth', 'omnisend_api_key',
        ]);
        expect(methods[0].oauth_provider).toBe('omnisend');
        expect(methods[0].oauth_scopes).toContain('brands.read');
        expect(methods[0].oauth_scopes).toContain('brands.write');
        expect(methods[1].method_kind).toBe('api_key');
    });
});
