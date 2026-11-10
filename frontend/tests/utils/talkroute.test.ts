import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { NODE_SCHEMA_TYPES } from '~/utils/nodeMeta';
import schema from '~/schemas/nodes/talkroute.json';

describe('Talkroute manual credentials', () => {
    it('discovers one API key method', () => {
        expect(NODE_SCHEMA_TYPES).toContain('automation-talkroute');
        const requirements = requirementsFromSchema(schema);
        expect(requirements).toHaveLength(1);
        expect(methodFromRequirement(requirements[0])).toMatchObject({
            credential_type: 'talkroute_api_key', method_kind: 'api_key', is_oauth: false,
        });
    });
});
