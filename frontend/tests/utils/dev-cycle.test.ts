import { describe, expect, it } from 'vitest';
import {
    methodFromRequirement,
    requirementsFromSchema,
} from '~/components/credential/credentialMethods';
import { NODE_SCHEMA_TYPES } from '~/utils/nodeMeta';
import schema from '~/schemas/nodes/dev-cycle.json';

describe('DevCycle credentials', () => {
    it('discovers a pasted management token through the shared credential method', () => {
        expect(NODE_SCHEMA_TYPES).toContain('automation-dev-cycle');
        const requirements = requirementsFromSchema(schema);
        expect(requirements).toHaveLength(1);
        expect(methodFromRequirement(requirements[0])).toMatchObject({
            credential_type: 'dev_cycle_access_token',
            method_kind: 'api_key',
            is_oauth: false,
        });
    });
});
