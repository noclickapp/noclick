// Agorapulse offers a manual API key form with no hidden required account fields.
// Pin the generated credential metadata used by connect and the public directory.
import { describe, expect, it } from 'vitest';
import { loadNodeSchemas } from '~/utils/nodeSchemas';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';

// Load the same lazy schema seam as the credential UI.
describe('Agorapulse credentials', () => {
    it('offers a manually supplied API key', async () => {
        await loadNodeSchemas(['automation-agorapulse']);
        const methods = credentialRequirements('automation-agorapulse').map(methodFromRequirement);
        expect(methods).toEqual([expect.objectContaining({ credential_type: 'agorapulse_api_key', method_kind: 'api_key', is_oauth: false })]);
    });
});
