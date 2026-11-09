import { beforeAll, expect, it } from 'vitest';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { CircleNode } from '~/components/workflow/nodes/integrations/circle';

beforeAll(() => loadNodeSchemas(['automation-circle']));
it('offers a pasted Circle token, community category and 25 admin operations', () => {
    expect(CircleNode.category).toBe('courses');
    expect(getNodeCredentialInfo('automation-circle')?.acceptedTypes).toEqual(['circle_api_token']);
    expect(getCredentialTypeFromSchemaTitle('Circle API Token')).toBe('circle_api_token');
    expect(credentialRequirements('automation-circle').map(methodFromRequirement).map(method => method.method_kind)).toEqual(['api_key']);
    const operations = getAgentToolOperations('automation-circle').map(op => op.operation);
    expect(operations).toHaveLength(25);
    for (const op of ['get_community', 'create_member', 'create_post', 'create_comment', 'tag_member', 'untag_member']) {
        expect(operations).toContain(op);
    }
});
