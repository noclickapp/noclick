// Pledge connections use a primary API key pasted by the account owner.
// This checks that schema discovery exposes the manual API-key connection method.
import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { loadNodeSchemas } from '~/utils/nodeSchemas';

await loadNodeSchemas(['automation-pledge']);

describe('Pledge manual connection', () => {
    it('offers a pasted API key', () => {
        const methods = credentialRequirements('automation-pledge').map(methodFromRequirement);
        expect(methods).toHaveLength(1);
        expect(methods[0]).toMatchObject({ credential_type: 'pledge_api_key', method_kind: 'api_key', is_oauth: false });
    });
});
