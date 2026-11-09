import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { NODE_SCHEMA_TYPES } from '~/utils/nodeMeta';
import schema from '~/schemas/nodes/blinq.json';
import { BlinqNode } from '~/components/workflow/nodes/integrations/blinq';

describe('Blinq integration', () => {
    it('discovers a manually pasted API key and CRM catalog category', () => {
        expect(NODE_SCHEMA_TYPES).toContain('automation-blinq');
        const requirements = requirementsFromSchema(schema);
        expect(requirements).toHaveLength(1);
        expect(methodFromRequirement(requirements[0])).toMatchObject({
            credential_type: 'blinq_api_key', method_kind: 'api_key', is_oauth: false,
        });
        expect(BlinqNode.category).toBe('crm-sales');
    });
});
