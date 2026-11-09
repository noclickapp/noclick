// Katana connects with a typed API key and must stay classified as a manual method.
// This guards the generated metadata used by all credential connect surfaces.
import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { loadNodeSchemas } from '~/utils/nodeSchemas';

await loadNodeSchemas(['automation-katana-mrp']);

describe('Katana manual connection', () => {
    it('offers the API key method', () => {
        const methods = credentialRequirements('automation-katana-mrp').map(methodFromRequirement);
        expect(methods).toEqual([expect.objectContaining({
            credential_type: 'katana_mrp_api_key', method_kind: 'api_key', is_oauth: false,
        })]);
    });
});
