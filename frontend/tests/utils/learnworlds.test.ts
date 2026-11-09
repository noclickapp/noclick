import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { NODE_SCHEMA_TYPES } from '~/utils/nodeMeta';
import schema from '~/schemas/nodes/learnworlds.json';

describe('LearnWorlds credentials', () => {
    it('offers a manually pasted access token', () => {
        expect(NODE_SCHEMA_TYPES).toContain('automation-learnworlds');
        const requirements = requirementsFromSchema(schema);
        expect(requirements).toHaveLength(1);
        expect(methodFromRequirement(requirements[0])).toMatchObject({
            credential_type: 'learnworlds_access_token', method_kind: 'api_key', is_oauth: false,
        });
    });
});
