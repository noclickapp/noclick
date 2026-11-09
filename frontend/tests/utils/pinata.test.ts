// Pinata offers one manually pasted JWT method with no OAuth prerequisites.
// This protects the generated connection catalog and automatic type selection.
import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';

await loadNodeSchemas(['automation-pinata']);

describe('Pinata connection method', () => {
    it('allows manual JWT connection', () => {
        const methods = credentialRequirements('automation-pinata').map(methodFromRequirement);
        expect(methods).toHaveLength(1);
        expect(methods[0]).toMatchObject({ credential_type: 'pinata_jwt', method_kind: 'api_key', is_oauth: false });
        expect(getNodeCredentialInfo('automation-pinata')?.acceptedTypes).toEqual(['pinata_jwt']);
    });
});
