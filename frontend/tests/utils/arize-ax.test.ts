// Verify the API key method exposed by generated Arize AX metadata.
// This keeps hand connecting and the catalog category aligned with the node.
import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { ArizeAxNode } from '~/components/workflow/nodes/integrations/arize-ax';
import { loadNodeSchemas, NODE_SCHEMAS } from '~/utils/nodeSchemas';

describe('Arize AX', () => {
    it('offers a manually pasted API key', async () => {
        await loadNodeSchemas(['automation-arize-ax']);
        const requirements = requirementsFromSchema(NODE_SCHEMAS['automation-arize-ax']);
        expect(requirements).toHaveLength(1);
        expect(methodFromRequirement(requirements[0])).toMatchObject({
            credential_type: 'arize_ax_api_key', method_kind: 'api_key', is_oauth: false,
        });
    });
    it('belongs in AI integrations', () => {
        expect(ArizeAxNode.category).toBe('ai');
        expect(ArizeAxNode.type).toBe('automation-arize-ax');
    });
});
