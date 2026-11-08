import { beforeAll, expect, it } from 'vitest';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { getNodeCredentialInfo, NODE_SCHEMAS, loadNodeSchemas } from '~/utils/nodeSchemas';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';

beforeAll(() => loadNodeSchemas(['automation-gender-api']));
it('discovers Gender API as one manual token method', () => {
    expect(getCredentialTypeFromSchemaTitle('GenderApiTokenCredential')).toBe('gender_api_token');
    expect(getCredentialTypeFromSchemaTitle('Gender API Token')).toBe('gender_api_token');
    expect(getNodeCredentialInfo('automation-gender-api')?.acceptedTypes).toEqual(['gender_api_token']);
    const requirements = requirementsFromSchema(NODE_SCHEMAS['automation-gender-api']);
    expect(requirements).toHaveLength(1);
    expect(methodFromRequirement(requirements[0]).method_kind).toBe('api_key');
    expect(methodFromRequirement(requirements[0]).is_oauth).toBe(false);
});
