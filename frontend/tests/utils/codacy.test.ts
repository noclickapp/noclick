import { beforeAll, expect, it } from 'vitest';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { getNodeCredentialInfo, NODE_SCHEMAS, loadNodeSchemas } from '~/utils/nodeSchemas';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';

beforeAll(() => loadNodeSchemas(['automation-codacy']));
it('discovers the Codacy token as one manual API key method', () => {
  expect(getCredentialTypeFromSchemaTitle('CodacyAPITokenCredential')).toBe('codacy_api_token');
  expect(getCredentialTypeFromSchemaTitle('Codacy API Token')).toBe('codacy_api_token');
  expect(getNodeCredentialInfo('automation-codacy')?.acceptedTypes).toEqual(['codacy_api_token']);
  const requirements = requirementsFromSchema(NODE_SCHEMAS['automation-codacy']);
  expect(requirements).toHaveLength(1);
  expect(methodFromRequirement(requirements[0]).method_kind).toBe('api_key');
  expect(methodFromRequirement(requirements[0]).is_oauth).toBe(false);
});
