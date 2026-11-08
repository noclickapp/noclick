import { beforeAll, expect, it } from 'vitest';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations, getNodeSchema } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';

beforeAll(() => loadNodeSchemas(['automation-brilliant-directories']));
it('offers the Brilliant Directories API key and directory URL connect form', () => {
    expect(getNodeCredentialInfo('automation-brilliant-directories')?.acceptedTypes).toEqual(['brilliant_directories_api_key']);
    expect(getNodeCredentialInfo('automation-brilliant-directories')?.label).toBe('Brilliant Directories API Key');
    const schema = getNodeSchema('automation-brilliant-directories');
    expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
    expect(getCredentialTypeFromSchemaTitle('Brilliant Directories API Key')).toBe('brilliant_directories_api_key');
});
it('offers member, lead, review and post workflows with discovery reads', () => {
    const operations = getAgentToolOperations('automation-brilliant-directories').map(op => op.operation);
    expect(operations).toHaveLength(20);
    expect(operations).toEqual(expect.arrayContaining(['create_member', 'update_lead', 'create_review', 'update_post', 'list_post_types', 'list_categories', 'list_membership_plans']));
});
