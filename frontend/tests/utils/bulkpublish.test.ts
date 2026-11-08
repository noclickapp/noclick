// Bulkpublish connects with a pasted API key and advertises its generated operations.
// This checks the same metadata used by the connect form and agent tool picker.
import { beforeAll, expect, it } from 'vitest';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';

beforeAll(() => loadNodeSchemas(['automation-bulkpublish']));
it('offers the Bulkpublish pasted key and publishing operations', () => {
    expect(getNodeCredentialInfo('automation-bulkpublish')?.acceptedTypes).toEqual(['bulkpublish_api_key']);
    expect(getCredentialTypeFromSchemaTitle('Bulkpublish API Key')).toBe('bulkpublish_api_key');
    expect(credentialRequirements('automation-bulkpublish').map(methodFromRequirement).map(method => method.method_kind)).toEqual(['api_key']);
    const operations = getAgentToolOperations('automation-bulkpublish').map(op => op.operation);
    expect(operations).toHaveLength(25);
    expect(operations).toContain('create_post');
    expect(operations).toContain('publish_post');
    expect(operations).toContain('get_analytics_engagement');
});
