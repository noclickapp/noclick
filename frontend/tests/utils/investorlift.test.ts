// Verifies that the generated InvestorLift metadata exposes one manual API-key connection.
// This guards the credential alias and method kind used by every connect surface.
import { beforeAll, expect, it } from 'vitest';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { getNodeCredentialInfo, NODE_SCHEMAS, loadNodeSchemas } from '~/utils/nodeSchemas';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';

beforeAll(() => loadNodeSchemas(['automation-investorlift']));
it('discovers the InvestorLift token as one manual API key method', () => {
  expect(getCredentialTypeFromSchemaTitle('InvestorLiftAPIKeyCredential')).toBe('investorlift_api_key');
  expect(getCredentialTypeFromSchemaTitle('InvestorLift API Key')).toBe('investorlift_api_key');
  expect(getNodeCredentialInfo('automation-investorlift')?.acceptedTypes).toEqual(['investorlift_api_key']);
  const requirements = requirementsFromSchema(NODE_SCHEMAS['automation-investorlift']);
  expect(requirements).toHaveLength(1);
  expect(methodFromRequirement(requirements[0]).method_kind).toBe('api_key');
  expect(methodFromRequirement(requirements[0]).is_oauth).toBe(false);
});
