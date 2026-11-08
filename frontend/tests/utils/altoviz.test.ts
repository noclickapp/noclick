import { beforeAll, expect, it } from 'vitest';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';

beforeAll(() => loadNodeSchemas(['automation-altoviz']));
it('offers the Altoviz pasted API key and 25 operations', () => {
    expect(getNodeCredentialInfo('automation-altoviz')?.acceptedTypes).toEqual(['altoviz_api_key']);
    expect(getCredentialTypeFromSchemaTitle('Altoviz API Key')).toBe('altoviz_api_key');
    expect(credentialRequirements('automation-altoviz').map(methodFromRequirement).map(method => method.method_kind)).toEqual(['api_key']);
    const operations = getAgentToolOperations('automation-altoviz').map(op => op.operation);
    expect(operations).toHaveLength(25);
    expect(operations).toContain('create_invoice');
    expect(operations).toContain('update_customer');
    expect(operations).toContain('get_settings');
});
