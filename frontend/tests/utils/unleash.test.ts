import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { NODE_SCHEMA_TYPES } from '~/utils/nodeMeta';
import { UnleashNode } from '~/components/workflow/nodes/integrations/unleash';
import schema from '~/schemas/nodes/unleash.json';

describe('Unleash connection', () => {
    it('discovers the manual access token and developer tools category', () => {
        expect(NODE_SCHEMA_TYPES).toContain('automation-unleash');
        expect(UnleashNode.category).toBe('developer-tools');
        const requirements = requirementsFromSchema(schema);
        expect(requirements).toHaveLength(1);
        expect(methodFromRequirement(requirements[0])).toMatchObject({
            credential_type: 'unleash_token', method_kind: 'api_key', is_oauth: false,
        });
    });
});
