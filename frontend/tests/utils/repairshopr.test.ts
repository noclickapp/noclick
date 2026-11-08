// RepairShopr uses the shared manual credential form with a pasted API token.
// This guards generated discovery and the method kind used on every connect surface.
import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { NODE_SCHEMA_TYPES } from '~/utils/nodeMeta';
import schema from '~/schemas/nodes/repairshopr.json';

describe('RepairShopr credential', () => {
    it('discovers one manual token method', () => {
        expect(NODE_SCHEMA_TYPES).toContain('automation-repairshopr');
        const requirements = requirementsFromSchema(schema);
        expect(requirements).toHaveLength(1);
        const method = methodFromRequirement(requirements[0]);
        expect(method.credential_type).toBe('repairshopr_api_token');
        expect(method.method_kind).toBe('api_key');
        expect(method.is_oauth).toBe(false);
    });
});
