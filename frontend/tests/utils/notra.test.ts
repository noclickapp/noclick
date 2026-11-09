import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { NODE_SCHEMA_TYPES } from '~/utils/nodeMeta';
import schema from '~/schemas/nodes/notra.json';

describe('Notra credentials', () => {
    it('discovers a manual API key with an optional workspace selector', () => {
        expect(NODE_SCHEMA_TYPES).toContain('automation-notra');
        const requirements = requirementsFromSchema(schema);
        expect(requirements).toHaveLength(1);
        const method = methodFromRequirement(requirements[0]);
        expect(method.credential_type).toBe('notra_api_key');
        expect(method.method_kind).toBe('api_key');
        expect(method.is_oauth).toBe(false);
        expect(schema.$defs.NotraAPIKeyCredential.required).toEqual(['api_key']);
        expect(schema.$defs.NotraAPIKeyCredential.properties.credential_type.default).toBe('notra_api_key');
    });
});
