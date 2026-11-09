import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';

import { loadNodeSchemas } from '~/utils/nodeSchemas';

await loadNodeSchemas(['automation-teamup']);

describe('TeamUp manual connection', () => {
    it('offers a pasted M2M token', () => {
        const requirements = credentialRequirements('automation-teamup');
        expect(requirements).toHaveLength(1);
        expect(methodFromRequirement(requirements[0])).toMatchObject({
            credential_type: 'teamup_m2m_token', method_kind: 'api_key', is_oauth: false,
        });
    });
});
