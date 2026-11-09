import { beforeAll, expect, it } from 'vitest';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';

beforeAll(() => loadNodeSchemas(['automation-squarespace-commerce']));
it('offers a manually pasted Squarespace Commerce API key and store operations', () => {
    expect(getNodeCredentialInfo('automation-squarespace-commerce')?.acceptedTypes).toEqual(['squarespace_commerce_api_key']);
    expect(getCredentialTypeFromSchemaTitle('Squarespace Commerce API Key')).toBe('squarespace_commerce_api_key');
    expect(credentialRequirements('automation-squarespace-commerce').map(methodFromRequirement).map(method => method.method_kind)).toEqual(['api_key']);
    const operations = getAgentToolOperations('automation-squarespace-commerce').map(op => op.operation);
    expect(operations).toHaveLength(15);
    expect(operations).toEqual(expect.arrayContaining(['get_website', 'adjust_inventory', 'fulfill_order', 'delete_product', 'list_profiles']));
});
