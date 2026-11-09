import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { NODE_SCHEMA_TYPES } from '~/utils/nodeMeta';
import schema from '~/schemas/nodes/propertyradar.json';

describe('PropertyRadar credentials', () => {
    it('discovers one manual token method with its human-fillable field', () => {
        expect(NODE_SCHEMA_TYPES).toContain('automation-propertyradar');
        const requirements = requirementsFromSchema(schema);
        expect(requirements).toHaveLength(1);
        const method = methodFromRequirement(requirements[0]);
        expect(method.credential_type).toBe('propertyradar_api_token');
        expect(method.method_kind).toBe('api_key');
        expect(method.is_oauth).toBe(false);
    });
});
