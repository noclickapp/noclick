import { describe, expect, it } from 'vitest';
import {
    methodFromRequirement,
    requirementsFromSchema,
} from '~/components/credential/credentialMethods';
import { NODE_SCHEMA_TYPES } from '~/utils/nodeMeta';
import schema from '~/schemas/nodes/nusii-proposals.json';

describe('Nusii Proposals credentials', () => {
    it('discovers a pasted API key through the shared credential method', () => {
        expect(NODE_SCHEMA_TYPES).toContain('automation-nusii-proposals');
        const requirements = requirementsFromSchema(schema);
        expect(requirements).toHaveLength(1);
        expect(methodFromRequirement(requirements[0])).toMatchObject({
            credential_type: 'nusii_proposals_api_key',
            method_kind: 'api_key',
            is_oauth: false,
        });
    });
});
