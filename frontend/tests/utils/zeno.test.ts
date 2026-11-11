import { beforeAll, expect, it } from 'vitest';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/zeno.json';

beforeAll(() => loadNodeSchemas(['automation-zeno']));

it('offers a manually pasted Zeno key and action tools', () => {
    expect(getNodeCredentialInfo('automation-zeno')?.acceptedTypes).toEqual(['zeno_api_key']);
    expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
    const operations = getAgentToolOperations('automation-zeno').map(op => op.operation);
    expect(operations).toHaveLength(22);
    expect(operations).toContain('publish_episode');
    expect(operations).toContain('get_transcript');
    expect(operations).not.toContain('on_new_video');
});
