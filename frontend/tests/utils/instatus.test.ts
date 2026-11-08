/** Verify the Instatus catalog exposes its personal-token connection method.
 * These checks pin the manual connection seam and discoverable operation metadata.
 */
import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { InstatusNode } from '../../app/components/workflow/nodes/integrations/instatus';
import { getAgentToolOperations, getNodeCredentialInfo, loadNodeSchemas } from '../../app/utils/nodeSchemas';

await loadNodeSchemas(['automation-instatus']);
describe('Instatus integration', () => {
    it('exposes its status-page operations in the monitoring category', () => {
        expect(InstatusNode.category).toBe('monitoring');
        expect(getAgentToolOperations('automation-instatus')).toHaveLength(23);
        expect(getAgentToolOperations('automation-instatus').map(o => o.operation)).toContain('create_incident_update');
    });
    it('connects using a pasted API token', () => {
        expect(credentialRequirements('automation-instatus').map(r => methodFromRequirement(r).method_kind)).toEqual(['api_key']);
        expect(getNodeCredentialInfo('automation-instatus')?.acceptedTypes).toContain('instatus_api_token');
    });
});
