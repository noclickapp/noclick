import { beforeAll, expect, it } from 'vitest';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { getNodeCredentialInfo, NODE_SCHEMAS, loadNodeSchemas } from '~/utils/nodeSchemas';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';

beforeAll(() => loadNodeSchemas(['automation-agiled']));
it('discovers the Agiled token as one manual API key method', () => {
  expect(getCredentialTypeFromSchemaTitle('AgiledAPITokenCredential')).toBe('agiled_api_token');
  expect(getCredentialTypeFromSchemaTitle('Agiled API Token')).toBe('agiled_api_token');
  expect(getNodeCredentialInfo('automation-agiled')?.acceptedTypes).toEqual(['agiled_api_token']);
  const requirements = requirementsFromSchema(NODE_SCHEMAS['automation-agiled']);
  expect(requirements).toHaveLength(1);
  expect(methodFromRequirement(requirements[0]).method_kind).toBe('api_key');
  expect(methodFromRequirement(requirements[0]).is_oauth).toBe(false);
});
