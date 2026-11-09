import { beforeAll, expect, it } from 'vitest';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { getNodeCredentialInfo, NODE_SCHEMAS, loadNodeSchemas } from '~/utils/nodeSchemas';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';

beforeAll(() => loadNodeSchemas(['automation-pocketsmith']));
it('discovers a manually connectable PocketSmith developer key', () => {
    expect(getCredentialTypeFromSchemaTitle('PocketSmithDeveloperKeyCredential')).toBe('pocketsmith_developer_key');
    expect(getCredentialTypeFromSchemaTitle('PocketSmith Developer Key')).toBe('pocketsmith_developer_key');
    expect(getNodeCredentialInfo('automation-pocketsmith')?.acceptedTypes).toEqual(['pocketsmith_developer_key']);
    const requirements = requirementsFromSchema(NODE_SCHEMAS['automation-pocketsmith']);
    expect(requirements).toHaveLength(1);
    expect(methodFromRequirement(requirements[0]).method_kind).toBe('api_key');
    expect(methodFromRequirement(requirements[0]).is_oauth).toBe(false);
});
