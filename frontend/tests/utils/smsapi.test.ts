import { beforeAll, expect, it } from 'vitest';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations, getNodeSchema } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';

beforeAll(() => loadNodeSchemas(['automation-smsapi']));
it('offers a manually connected token with the SMSAPI name', () => {
    const schema = getNodeSchema('automation-smsapi');
    expect(getNodeCredentialInfo('automation-smsapi')?.acceptedTypes).toEqual(['smsapi_api_token']);
    expect(getNodeCredentialInfo('automation-smsapi')?.label).toBe('SMSAPI API Token');
    expect(methodFromRequirement(requirementsFromSchema(schema)[0])).toMatchObject({ method_kind: 'api_key', is_oauth: false });
    expect(getCredentialTypeFromSchemaTitle('SMSAPI API Token')).toBe('smsapi_api_token');
});
it('makes all 22 read and write operations available to agents', () => {
    const operations = getAgentToolOperations('automation-smsapi').map(op => op.operation);
    expect(operations).toHaveLength(22);
    expect(operations).toEqual(expect.arrayContaining(['get_profile', 'send_sms', 'create_contact', 'update_group', 'remove_contact_from_group', 'delete_template']));
});
