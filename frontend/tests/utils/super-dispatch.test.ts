import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { NODE_SCHEMA_TYPES } from '~/utils/nodeMeta';
import schema from '~/schemas/nodes/super-dispatch.json';

describe('Super Dispatch credential', () => {
    it('discovers the manual Carrier API key method', () => {
        expect(NODE_SCHEMA_TYPES).toContain('automation-super-dispatch');
        const requirements = requirementsFromSchema(schema);
        expect(requirements).toHaveLength(1);
        expect(methodFromRequirement(requirements[0])).toMatchObject({
            credential_type: 'super_dispatch_api_key', method_kind: 'api_key', is_oauth: false,
        });
    });
});
