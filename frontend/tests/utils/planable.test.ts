// Checks discovery of the generated Planable credential and operation metadata.
// This keeps manual token connection and catalog categorization aligned with the node.
import { beforeAll, expect, it } from 'vitest';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { PlanableNode } from '~/components/workflow/nodes/integrations/planable';

beforeAll(async () => { await loadNodeSchemas(['automation-planable']); });
it('discovers Planable with manual token authentication and social media operations', () => {
    expect(PlanableNode.category).toBe('social-media');
    expect(getNodeCredentialInfo(PlanableNode.type)?.acceptedTypes).toEqual(['planable_api_token']);
    expect(credentialRequirements(PlanableNode.type).map(methodFromRequirement)).toEqual([
        expect.objectContaining({ credential_type: 'planable_api_token', method_kind: 'api_key', is_oauth: false }),
    ]);
    const operations = getAgentToolOperations(PlanableNode.type).map(op => op.operation);
    expect(operations).toHaveLength(25);
    expect(operations).toEqual(expect.arrayContaining(['list_workspaces', 'create_post', 'update_post', 'request_approval', 'upload_media']));
});
