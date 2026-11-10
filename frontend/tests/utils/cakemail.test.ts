import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { loadNodeSchemas } from '~/utils/nodeSchemas';

await loadNodeSchemas(['automation-cakemail']);

describe('Cakemail manual connection', () => {
    it('offers a pasted API key', () => {
        const methods = credentialRequirements('automation-cakemail').map(methodFromRequirement);
        expect(methods).toHaveLength(1);
        expect(methods[0]).toMatchObject({ credential_type: 'cakemail_token', method_kind: 'api_key', is_oauth: false });
    });
});
