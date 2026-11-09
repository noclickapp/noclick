import { beforeAll, expect, it } from 'vitest';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { CypherLearningNode } from '~/components/workflow/nodes/integrations/cypher-learning';

beforeAll(async () => { await loadNodeSchemas(['automation-cypher-learning']); });
it('discovers CYPHER Learning with a manual API key and 22 operations', () => {
    expect(CypherLearningNode.category).toBe('courses');
    expect(getNodeCredentialInfo(CypherLearningNode.type)?.acceptedTypes).toEqual(['cypher_learning_api_key']);
    expect(credentialRequirements(CypherLearningNode.type).map(methodFromRequirement)).toEqual([
        expect.objectContaining({ credential_type: 'cypher_learning_api_key', method_kind: 'api_key', is_oauth: false }),
    ]);
    const operations = getAgentToolOperations(CypherLearningNode.type).map(op => op.operation);
    expect(operations).toHaveLength(22);
    expect(operations).toEqual(expect.arrayContaining(['list_classes', 'create_user', 'update_user', 'add_class_student', 'update_class_student', 'remove_class_student', 'create_group', 'add_group_member', 'list_assignment_grades']));
});
