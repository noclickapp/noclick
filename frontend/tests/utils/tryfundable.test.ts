// Exercises Tryfundable's manual connection metadata through the shared catalog.
// Keeps the pasted API key method discoverable without an OAuth sign-in.
import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { loadNodeSchemas } from '~/utils/nodeSchemas';

await loadNodeSchemas(['automation-tryfundable']);

describe('Tryfundable manual connection', () => {
    it('offers a pasted API key', () => {
        const methods = credentialRequirements('automation-tryfundable').map(methodFromRequirement);
        expect(methods).toHaveLength(1);
        expect(methods[0]).toMatchObject({ credential_type: 'tryfundable_api_key', method_kind: 'api_key', is_oauth: false });
    });
});
