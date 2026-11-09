// Verifies Mihu Ai's generated credential metadata and manual connection method.
// It also pins the operation catalog exposed to workflow and agent tools.
import { beforeAll, expect, it } from 'vitest';
import { loadNodeSchemas, NODE_SCHEMAS, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';

beforeAll(() => loadNodeSchemas(['automation-mihu-ai']));
it('connects by hand using a Mihu Ai API token', () => {
    expect(getNodeCredentialInfo('automation-mihu-ai')?.acceptedTypes).toEqual(['mihu_ai_api_token']);
    expect(requirementsFromSchema(NODE_SCHEMAS['automation-mihu-ai']).map(methodFromRequirement)).toEqual([
        expect.objectContaining({ method_kind: 'api_key', is_oauth: false }),
    ]);
});
it('exposes twenty two documented operations', () => {
    expect(getAgentToolOperations('automation-mihu-ai')).toHaveLength(22);
});
