import { beforeAll, expect, it } from 'vitest';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { getNodeCredentialInfo, NODE_SCHEMAS, loadNodeSchemas } from '~/utils/nodeSchemas';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';

beforeAll(() => loadNodeSchemas(['automation-heygen']));
it('discovers HeyGen as a manual API key connection', () => {
    expect(getCredentialTypeFromSchemaTitle('HeyGenAPIKey')).toBe('heygen_api_key');
    expect(getCredentialTypeFromSchemaTitle('Heygen API Key')).toBe('heygen_api_key');
    expect(getNodeCredentialInfo('automation-heygen')?.acceptedTypes).toEqual(['heygen_api_key']);
    const requirements = requirementsFromSchema(NODE_SCHEMAS['automation-heygen']);
    expect(requirements).toHaveLength(1);
    expect(methodFromRequirement(requirements[0]).method_kind).toBe('api_key');
    expect(methodFromRequirement(requirements[0]).is_oauth).toBe(false);
});
