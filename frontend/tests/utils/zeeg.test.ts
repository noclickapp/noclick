// Zeeg's discovered metadata exposes its scheduling tools and pasted-token connection.
// This protects the public bookings category and generated manual-connect contract.
import { expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { ZeegNode } from '../../app/components/workflow/nodes/integrations/zeeg';
import { getAgentToolOperations, getNodeCredentialInfo, loadNodeSchemas } from '../../app/utils/nodeSchemas';

await loadNodeSchemas(['automation-zeeg']);
it('discovers Zeeg scheduling operations and manual token credentials', () => {
    expect(ZeegNode.category).toBe('bookings');
    expect(getAgentToolOperations('automation-zeeg').map(o => o.operation)).toHaveLength(24);
    expect(credentialRequirements('automation-zeeg').map(r => methodFromRequirement(r).method_kind)).toEqual(['api_key']);
    expect(getNodeCredentialInfo('automation-zeeg')?.acceptedTypes).toEqual(['zeeg_api_token']);
});
