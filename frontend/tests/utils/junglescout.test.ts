import { beforeAll, expect, it } from 'vitest';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { getNodeCredentialInfo, NODE_SCHEMAS, loadNodeSchemas } from '~/utils/nodeSchemas';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';

beforeAll(() => loadNodeSchemas(['automation-junglescout']));
it('discovers Jungle Scout as one manual API key method', () => {
  expect(getCredentialTypeFromSchemaTitle('JunglescoutAPIKeyCredential')).toBe('junglescout_api_key');
  expect(getCredentialTypeFromSchemaTitle('Jungle Scout API Key')).toBe('junglescout_api_key');
  expect(getNodeCredentialInfo('automation-junglescout')?.acceptedTypes).toEqual(['junglescout_api_key']);
  const requirements = requirementsFromSchema(NODE_SCHEMAS['automation-junglescout']);
  expect(requirements).toHaveLength(1);
  expect(methodFromRequirement(requirements[0]).method_kind).toBe('api_key');
  expect(methodFromRequirement(requirements[0]).is_oauth).toBe(false);
});
