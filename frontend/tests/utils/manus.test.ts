import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { NODE_SCHEMA_TYPES } from '~/utils/nodeMeta';
import schema from '~/schemas/nodes/manus.json';

describe('Manus credentials', () => {
    it('discovers a pasted API key with no OAuth sign-in', () => {
        expect(NODE_SCHEMA_TYPES).toContain('automation-manus');
        const requirements = requirementsFromSchema(schema);
        expect(requirements).toHaveLength(1);
        expect(methodFromRequirement(requirements[0])).toMatchObject({
            credential_type: 'manus_api_key', method_kind: 'api_key', is_oauth: false,
        });
    });
});
