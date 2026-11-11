import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { loadNodeSchemas } from '~/utils/nodeSchemas';
import { GoogleBooksNode } from '~/components/workflow/nodes/integrations/google-books';

await loadNodeSchemas(['automation-google-books']);

describe('Google Books credential and catalog', () => {
    it('uses Google OAuth and appears in the Google section', () => {
        const methods = credentialRequirements('automation-google-books').map(methodFromRequirement);
        expect(methods).toHaveLength(2);
        expect(methods.map(method => method.method_kind)).toEqual(['oauth', 'api_key']);
        expect(GoogleBooksNode.category).toBe('google');
    });
});
