// Pin the Revolut Business manual connection and discoverable category.
// These checks cover the generated metadata used by hosted connect surfaces.
import { describe, expect, it } from 'vitest';
import { loadNodeSchemas } from '~/utils/nodeSchemas';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { RevolutBusinessNode } from '~/components/workflow/nodes/integrations/revolut-for-business';

describe('Revolut Business', () => {
    it('connects manually with a prepared access token', async () => {
        await loadNodeSchemas(['automation-revolut-for-business']);
        const requirements = credentialRequirements('automation-revolut-for-business');
        expect(requirements).toHaveLength(1);
        const method = methodFromRequirement(requirements[0]);
        expect(method.credential_type).toBe('revolut_business_access_token');
        expect(method.method_kind).toBe('api_key');
        expect(method.credential_fields?.map(f => f.name)).toContain('access_token');
    });
    it('belongs to finance and accounting', () => {
        expect(RevolutBusinessNode.category).toBe('finance-accounting');
    });
});
