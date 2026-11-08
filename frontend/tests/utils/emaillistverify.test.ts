import { beforeAll, expect, it } from 'vitest';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';

beforeAll(() => loadNodeSchemas(['automation-emaillistverify']));
it('offers the API key and the published reads and writes', async () => {
    const { NODE_SCHEMAS } = await import('~/utils/nodeSchemas');
    const info = getNodeCredentialInfo('automation-emaillistverify');
    expect(info?.acceptedTypes).toEqual(['emaillistverify_api_key']);
    expect(info?.label).toBe('EmailListVerify API Key');
    expect(methodFromRequirement(requirementsFromSchema(NODE_SCHEMAS['automation-emaillistverify'])[0]).method_kind).toBe('api_key');
    const ops = getAgentToolOperations('automation-emaillistverify').map(op => op.operation);
    expect(ops).toHaveLength(14);
    expect(ops).toContain('get_credits');
    expect(ops).toContain('create_email_job');
    expect(ops).toContain('delete_list');
});
