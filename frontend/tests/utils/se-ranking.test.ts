import { beforeAll, describe, expect, it } from 'vitest';
import schema from '~/schemas/nodes/se-ranking.json';
import { SERankingNode } from '~/components/workflow/nodes/integrations/se-ranking';
import { getAgentToolOperations, getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';

const type = 'automation-se-ranking';
beforeAll(() => loadNodeSchemas([type]));

describe('SE Ranking native integration', () => {
    it('discovers its definition, credential and fourteen operations', () => {
        expect(SERankingNode.type).toBe(type);
        expect(getNodeCredentialInfo(type)?.acceptedTypes).toEqual(['se_ranking_api_token']);
        expect(getAgentToolOperations(type)).toHaveLength(14);
        expect(schema.$defs.GetKeywordPositions.properties.site_engine_id['x-dynamic-options'].depends_on).toBe('site_id');
        expect(schema.$defs.GetKeywordPositions.properties.keyword_id['x-dynamic-options'].depends_on).toBe('site_engine_id');
    });
    it('uses the manual token method with all account boundary fields', () => {
        const requirements = requirementsFromSchema(schema);
        expect(requirements).toHaveLength(1);
        const method = methodFromRequirement(requirements[0]);
        expect(method.method_kind).toBe('api_key');
        expect(method.is_oauth).toBe(false);
        expect(method.credential_fields?.map(field => [field.name, field.type, field.required])).toEqual([
            ['api_token', 'password', true], ['expected_email', 'text', true], ['project_ids', 'text', true],
        ]);
    });
});
