import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { loadNodeSchemas } from '~/utils/nodeSchemas';

await loadNodeSchemas(['automation-pims']);

describe('Pims connection', () => {
    it('offers a manual API account with no OAuth installation', () => {
        const requirements = credentialRequirements('automation-pims');
        expect(requirements).toHaveLength(1);
        expect(methodFromRequirement(requirements[0])).toMatchObject({
            credential_type: 'pims_basic', method_kind: 'api_key', is_oauth: false,
        });
    });
});
