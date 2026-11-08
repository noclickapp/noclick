import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { NODE_SCHEMA_TYPES } from '~/utils/nodeMeta';
import schema from '~/schemas/nodes/elai.json';

describe('Elai credentials', () => {
    it('discovers a manually pasted API token', () => {
        expect(NODE_SCHEMA_TYPES).toContain('automation-elai');
        const requirements = requirementsFromSchema(schema);
        expect(requirements).toHaveLength(1);
        expect(methodFromRequirement(requirements[0])).toMatchObject({
            credential_type: 'elai_api_token', method_kind: 'api_key', is_oauth: false,
        });
    });
});
