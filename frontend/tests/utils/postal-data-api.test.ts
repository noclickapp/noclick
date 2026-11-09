// Checks the discovered Postal Data Api catalog and manual connection method.
// This guards the public labels and credential metadata generated from the node.
import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { PostalDataApiNode } from '../../app/components/workflow/nodes/integrations/postal-data-api';
import { getAgentToolOperations, getNodeCredentialInfo, loadNodeSchemas } from '../../app/utils/nodeSchemas';

await loadNodeSchemas(['automation-postal-data-api']);
describe('Postal Data Api integration', () => {
    it('discovers the complete six-operation contract', () => {
        expect(PostalDataApiNode.category).toBe('developer-tools');
        expect(getAgentToolOperations('automation-postal-data-api')).toHaveLength(6);
    });
    it('connects with a pasted API key', () => {
        expect(credentialRequirements('automation-postal-data-api').map(r => methodFromRequirement(r).method_kind)).toEqual(['api_key']);
        expect(getNodeCredentialInfo('automation-postal-data-api')?.acceptedTypes).toContain('postal_data_api_key');
    });
});
