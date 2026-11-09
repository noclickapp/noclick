import { describe, expect, it } from 'vitest';
import {
    methodFromRequirement,
    requirementsFromSchema,
} from '~/components/credential/credentialMethods';
import { NODE_SCHEMA_TYPES } from '~/utils/nodeMeta';
import { loadNodeSchemas, getNodeSchema } from '~/utils/nodeSchemas';

describe('InvestorBase credentials', () => {
    it('discovers a manual API key with its subscriber and enterprise context', async () => {
        expect(NODE_SCHEMA_TYPES).toContain('automation-investorbase');
        await loadNodeSchemas(['automation-investorbase']);
        const info = getNodeSchema('automation-investorbase');
        const requirements = requirementsFromSchema(info);
        expect(requirements).toHaveLength(1);
        const method = methodFromRequirement(requirements[0]);
        expect(method).toMatchObject({
            credential_type: 'investorbase_api_key',
            method_kind: 'api_key',
            is_oauth: false,
        });
        expect(method.credential_fields?.map((field) => field.name)).toEqual([
            'api_key',
            'key_kind',
            'enterprise_user_id',
        ]);
    });
});
