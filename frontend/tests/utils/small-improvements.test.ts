import { expect, it } from 'vitest';
import {
    methodFromRequirement,
    requirementsFromSchema,
} from '~/components/credential/credentialMethods';
import { NODE_SCHEMA_TYPES } from '~/utils/nodeMeta';
import { loadNodeSchemas, getNodeSchema } from '~/utils/nodeSchemas';
import { SmallImprovementsNode } from '~/components/workflow/nodes/integrations/small-improvements';

it('discovers Small Improvements with a manually pasted token and HR category', async () => {
    expect(NODE_SCHEMA_TYPES).toContain('automation-small-improvements');
    await loadNodeSchemas(['automation-small-improvements']);
    const requirements = requirementsFromSchema(
        getNodeSchema('automation-small-improvements')
    );
    expect(requirements).toHaveLength(1);
    expect(methodFromRequirement(requirements[0])).toMatchObject({
        credential_type: 'small_improvements_personal_access_token',
        method_kind: 'api_key',
        is_oauth: false,
    });
    expect(SmallImprovementsNode.category).toBe('hr-recruiting');
});
