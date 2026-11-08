import { describe, it, expect } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { loadNodeSchemas } from '~/utils/nodeSchemas';

describe('Corrently manual connection', () => {
    it('discovers the meter secret as a manual credential', async () => {
        await loadNodeSchemas(['automation-corrently']);
        const requirements = credentialRequirements('automation-corrently');
        expect(requirements).toHaveLength(1);
        expect(methodFromRequirement(requirements[0]).method_kind).toBe('api_key');
    });
});
