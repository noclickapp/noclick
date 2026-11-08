// AgencyZoom uses a pasted bearer token throughout the shared connect UI.
// This guards discovery and prevents its token method from becoming an OAuth flow.
import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { NODE_SCHEMA_TYPES } from '~/utils/nodeMeta';
import schema from '~/schemas/nodes/agencyzoom.json';

describe('AgencyZoom credentials', () => {
    it('discovers one manual bearer token method', () => {
        expect(NODE_SCHEMA_TYPES).toContain('automation-agencyzoom');
        const requirements = requirementsFromSchema(schema);
        expect(requirements).toHaveLength(1);
        const method = methodFromRequirement(requirements[0]);
        expect(method.credential_type).toBe('agencyzoom_bearer_token');
        expect(method.method_kind).toBe('api_key');
        expect(method.is_oauth).toBe(false);
    });
});
