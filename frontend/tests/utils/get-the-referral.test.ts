import { beforeAll, expect, it } from 'vitest';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import schema from '~/schemas/nodes/get-the-referral.json';

beforeAll(() => loadNodeSchemas(['automation-get-the-referral']));
it('offers a manual API key with the Get The Referral provider label', () => {
    expect(getNodeCredentialInfo('automation-get-the-referral')?.acceptedTypes).toEqual(['get_the_referral_api_key']);
    expect(getNodeCredentialInfo('automation-get-the-referral')?.label).toBe('Get The Referral API Key');
    expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
    expect(getCredentialTypeFromSchemaTitle('Get The Referral API Key')).toBe('get_the_referral_api_key');
});
it('exposes the 21 referral operations to agents', () => {
    const operations = getAgentToolOperations('automation-get-the-referral').map(op => op.operation);
    expect(operations).toHaveLength(21);
    expect(operations).toEqual(expect.arrayContaining(['list_advocates', 'create_lead', 'update_lead_status', 'delete_contact', 'list_wallet_transactions']));
});
