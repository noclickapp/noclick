import { beforeAll, expect, it } from 'vitest';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';

beforeAll(() => loadNodeSchemas(['automation-bulksmscom']));
it('offers a pasted BulkSMS.com API token and twelve operations', () => {
    expect(getNodeCredentialInfo('automation-bulksmscom')?.acceptedTypes).toEqual(['bulksmscom_api_token']);
    expect(getCredentialTypeFromSchemaTitle('BulkSMS.com API Token')).toBe('bulksmscom_api_token');
    expect(credentialRequirements('automation-bulksmscom').map(methodFromRequirement).map(method => method.method_kind)).toEqual(['api_key']);
    const operations = getAgentToolOperations('automation-bulksmscom').map(op => op.operation);
    expect(operations).toHaveLength(12);
    expect(operations).toContain('send_messages');
    expect(operations).toContain('get_profile');
    expect(operations).toContain('update_webhook');
});
