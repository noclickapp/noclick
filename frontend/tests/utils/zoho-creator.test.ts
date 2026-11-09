import { beforeAll, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { loadNodeSchemas } from '~/utils/nodeSchemas';
beforeAll(() => loadNodeSchemas(['automation-zoho-creator']));
import { ZohoCreatorNode } from '~/components/workflow/nodes/integrations/zoho-creator';

it('connects Zoho Creator through the declared OAuth provider', () => {
    expect(ZohoCreatorNode.type).toBe('automation-zoho-creator');
    expect(ZohoCreatorNode.label).toBe('Zoho Creator');
    const requirements = credentialRequirements(ZohoCreatorNode.type);
    expect(requirements).toHaveLength(1);
    expect(methodFromRequirement(requirements[0])).toMatchObject({
        credential_type: 'zoho_creator_oauth', method_kind: 'oauth',
        is_oauth: true, oauth_provider: 'zoho_creator',
    });
});
