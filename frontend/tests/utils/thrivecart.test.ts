import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { NODE_SCHEMA_TYPES } from '~/utils/nodeMeta';
import schema from '~/schemas/nodes/thrivecart.json';

describe('ThriveCart credentials', () => {
    it('discovers one manual API key method', () => {
        expect(NODE_SCHEMA_TYPES).toContain('automation-thrivecart');
        const requirements = requirementsFromSchema(schema);
        expect(requirements).toHaveLength(1);
        expect(methodFromRequirement(requirements[0])).toMatchObject({
            credential_type: 'thrivecart_api_key', method_kind: 'api_key', is_oauth: false,
        });
    });
});
