import { describe, expect, it } from 'vitest';
import { BscDesignerNode } from '~/components/workflow/nodes/integrations/bsc-designer';
import { loadNodeSchemas, NODE_SCHEMAS } from '~/utils/nodeSchemas';
import {
    requirementsFromSchema,
    methodFromRequirement,
} from '~/components/credential/credentialMethods';

describe('BSC Designer integration', () => {
    it('offers a manual API token connection in analytics and BI', async () => {
        await loadNodeSchemas(['automation-bsc-designer']);
        expect(BscDesignerNode.category).toBe('analytics-bi');
        const requirements = requirementsFromSchema(
            NODE_SCHEMAS['automation-bsc-designer']
        );
        expect(requirements).toHaveLength(1);
        expect(methodFromRequirement(requirements[0])).toMatchObject({
            credential_type: 'bsc_designer_api_token',
            method_kind: 'api_key',
            is_oauth: false,
        });
    });
});
