import { beforeAll, expect, it } from 'vitest';
import { PodiumNode } from '~/components/workflow/nodes/integrations/podium';
import { getNodeCredentialInfo, NODE_SCHEMAS, loadNodeSchemas } from '~/utils/nodeSchemas';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';

beforeAll(() => loadNodeSchemas(['automation-podium']));
it('discovers Podium with its declared OAuth connection and category', () => {
    expect(PodiumNode.type).toBe('automation-podium');
    expect(PodiumNode.category).toBe('communication');
    expect(getNodeCredentialInfo('automation-podium')?.acceptedTypes).toEqual(['podium_oauth']);
    const methods = requirementsFromSchema(NODE_SCHEMAS['automation-podium']).map(methodFromRequirement);
    expect(methods).toHaveLength(1);
    expect(methods[0]).toMatchObject({ credential_type: 'podium_oauth', method_kind: 'oauth', is_oauth: true });
});
