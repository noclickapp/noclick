import { describe, expect, it } from 'vitest';
import schema from '../../app/schemas/nodes/netlify.json';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';
import { NetlifyNode } from '~/components/workflow/nodes/integrations/netlify';

describe('Netlify integration', () => {
    it('offers an OAuth sign-in and a personal access token', () => {
        expect(NetlifyNode.type).toBe('automation-netlify');
        expect(requirementsFromSchema(schema).map(req => {
            const method = methodFromRequirement(req);
            return [req.credential_type, method.method_kind];
        })).toEqual([['netlify_oauth', 'oauth'], ['netlify_pat', 'api_key']]);
    });
});
