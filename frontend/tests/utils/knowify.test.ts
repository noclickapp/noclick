import { beforeAll, describe, expect, it } from 'vitest';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';
import { NODE_SCHEMAS, loadNodeSchemas } from '~/utils/nodeSchemas';
import { KnowifyNode } from '~/components/workflow/nodes/integrations/knowify';


beforeAll(() => loadNodeSchemas(['automation-knowify']));

describe('Knowify connection method', () => {
    it('exposes a manual session token and industry category', () => {
        const requirements = requirementsFromSchema(NODE_SCHEMAS['automation-knowify']);
        expect(requirements).toHaveLength(1);
        expect(methodFromRequirement(requirements[0])).toMatchObject({
            credential_type: 'knowify_session_token', method_kind: 'api_key', is_oauth: false,
        });
        expect(KnowifyNode.category).toBe('industry');
    });
});
