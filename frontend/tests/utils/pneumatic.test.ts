import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { NODE_SCHEMA_TYPES } from '~/utils/nodeMeta';
import schema from '~/schemas/nodes/pneumatic.json';

describe('Pneumatic manual connection', () => {
    it('discovers the API key with one person-supplied secret', () => {
        expect(NODE_SCHEMA_TYPES).toContain('automation-pneumatic');
        const requirements = requirementsFromSchema(schema);
        expect(requirements).toHaveLength(1);
        const method = methodFromRequirement(requirements[0]);
        expect(method).toMatchObject({ credential_type: 'pneumatic_api_key', method_kind: 'api_key', is_oauth: false });
        expect(method.credential_fields?.map((field) => field.name)).toEqual(['api_key']);
    });
});
