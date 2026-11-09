import { beforeAll, expect, it } from 'vitest';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { EMnifyNode } from '~/components/workflow/nodes/integrations/emnify';

beforeAll(async () => { await loadNodeSchemas(['automation-emnify']); });
it('discovers EMnify with manual application-token auth and 21 operations', () => {
    expect(EMnifyNode.category).toBe('industry');
    expect(getNodeCredentialInfo(EMnifyNode.type)?.acceptedTypes).toEqual(['emnify_application_token']);
    expect(credentialRequirements(EMnifyNode.type).map(methodFromRequirement)).toEqual([
        expect.objectContaining({ credential_type: 'emnify_application_token', method_kind: 'api_key', is_oauth: false }),
    ]);
    const operations = getAgentToolOperations(EMnifyNode.type).map(op => op.operation);
    expect(operations).toHaveLength(21);
    expect(operations).toEqual(expect.arrayContaining(['get_organisation', 'send_sms', 'reset_connectivity', 'update_endpoint', 'set_data_quota']));
});
