// PlanetScale uses a pasted service token throughout the shared connect UI.
// This guards discovery and prevents its token method from becoming an OAuth flow.
import { describe, expect, it } from 'vitest';
import {
    methodFromRequirement,
    requirementsFromSchema,
} from '~/components/credential/credentialMethods';
import { NODE_SCHEMA_TYPES } from '~/utils/nodeMeta';
import schema from '~/schemas/nodes/planetscale.json';

describe('PlanetScale credentials', () => {
    it('discovers one manual service token method', () => {
        expect(NODE_SCHEMA_TYPES).toContain('automation-planetscale');
        const requirements = requirementsFromSchema(schema);
        expect(requirements).toHaveLength(1);
        const method = methodFromRequirement(requirements[0]);
        expect(method.credential_type).toBe('planetscale_service_token');
        expect(method.method_kind).toBe('api_key');
        expect(method.is_oauth).toBe(false);
    });
});
