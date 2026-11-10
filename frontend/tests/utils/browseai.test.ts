import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { loadNodeSchemas } from '~/utils/nodeSchemas';

await loadNodeSchemas(['automation-browseai']);

describe('Browse AI manual connection', () => {
    it('offers a pasted API key', () => {
        const methods = credentialRequirements('automation-browseai').map(methodFromRequirement);
        expect(methods).toHaveLength(1);
        expect(methods[0]).toMatchObject({ credential_type: 'browseai_api_key', method_kind: 'api_key', is_oauth: false });
    });
});
