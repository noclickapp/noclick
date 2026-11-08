import { beforeAll, expect, it } from 'vitest';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations, NODE_SCHEMAS } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';

beforeAll(() => loadNodeSchemas(['automation-orshot']));
it('offers Orshot through a manual workspace API key', () => {
    expect(getNodeCredentialInfo('automation-orshot')?.acceptedTypes).toEqual(['orshot_api_key']);
    expect(getNodeCredentialInfo('automation-orshot')?.label).toBe('Orshot API Key');
    const schema = NODE_SCHEMAS['automation-orshot'];
    expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
});
it('exposes rendering plus template, folder, job and asset operations', () => {
    const operations = getAgentToolOperations('automation-orshot').map(op => op.operation);
    expect(operations).toHaveLength(21);
    for (const operation of ['render_template', 'get_render_job', 'list_templates', 'create_folder', 'upload_image', 'get_workspace']) {
        expect(operations).toContain(operation);
    }
});
