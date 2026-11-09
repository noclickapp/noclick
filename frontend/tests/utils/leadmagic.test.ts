import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { NODE_SCHEMA_TYPES } from '~/utils/nodeMeta';
import schema from '~/schemas/nodes/leadmagic.json';

describe('LeadMagic credentials', () => {
    it('discovers a manually pasted API key', () => {
        expect(NODE_SCHEMA_TYPES).toContain('automation-leadmagic');
        const requirements = requirementsFromSchema(schema);
        expect(requirements).toHaveLength(1);
        expect(methodFromRequirement(requirements[0])).toMatchObject({
            credential_type: 'leadmagic_api_key', method_kind: 'api_key', is_oauth: false,
        });
    });
});
