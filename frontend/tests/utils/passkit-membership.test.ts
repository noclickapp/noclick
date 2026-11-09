import { expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { NODE_SCHEMA_TYPES } from '~/utils/nodeMeta';
import { loadNodeSchemas, getNodeSchema } from '~/utils/nodeSchemas';
import { PassKitMembershipNode } from '~/components/workflow/nodes/integrations/passkit-membership';

it('discovers PassKit Membership with a manual token connection', async () => {
    expect(NODE_SCHEMA_TYPES).toContain('automation-passkit-membership');
    await loadNodeSchemas(['automation-passkit-membership']);
    const requirements = requirementsFromSchema(getNodeSchema('automation-passkit-membership'));
    expect(requirements).toHaveLength(1);
    expect(methodFromRequirement(requirements[0])).toMatchObject({ credential_type: 'passkit_membership_api_token', method_kind: 'api_key', is_oauth: false });
    expect(PassKitMembershipNode.category).toBe('marketing');
});
