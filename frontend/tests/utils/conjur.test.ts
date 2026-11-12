import { expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { loadNodeSchemas } from '~/utils/nodeSchemas';

await loadNodeSchemas(['automation-conjur']);
it('offers a manually pasted Conjur API key', () => {
    const methods = credentialRequirements('automation-conjur').map(methodFromRequirement);
    expect(methods).toHaveLength(1);
    expect(methods[0]).toMatchObject({ credential_type: 'conjur_api_key', method_kind: 'api_key', is_oauth: false });
});
