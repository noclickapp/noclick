import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { NODE_SCHEMA_TYPES } from '~/utils/nodeMeta';
import { getNodeSchema, loadNodeSchemas } from '~/utils/nodeSchemas';

describe('VaultRE credentials', () => {
    it('discovers one manual method with two supplied secrets', async () => {
        expect(NODE_SCHEMA_TYPES).toContain('automation-vaultre');
        await loadNodeSchemas(['automation-vaultre']);
        const schema = getNodeSchema('automation-vaultre');
        const requirements = requirementsFromSchema(schema!);
        expect(requirements).toHaveLength(1);
        expect(methodFromRequirement(requirements[0])).toMatchObject({
            credential_type: 'vaultre_api_key', method_kind: 'api_key', is_oauth: false,
        });
    });
});
