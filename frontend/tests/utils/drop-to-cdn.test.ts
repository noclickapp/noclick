import { beforeAll, expect, it } from 'vitest';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { getNodeCredentialInfo, NODE_SCHEMAS, loadNodeSchemas } from '~/utils/nodeSchemas';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';

beforeAll(() => loadNodeSchemas(['automation-drop-to-cdn']));
it('discovers the Drop To Cdn token as one manual API key method', () => {
  expect(getCredentialTypeFromSchemaTitle('DropToCdnAPIKeyCredential')).toBe('drop_to_cdn_api_key');
  expect(getCredentialTypeFromSchemaTitle('Drop To Cdn API Key')).toBe('drop_to_cdn_api_key');
  expect(getNodeCredentialInfo('automation-drop-to-cdn')?.acceptedTypes).toEqual(['drop_to_cdn_api_key']);
  const requirements = requirementsFromSchema(NODE_SCHEMAS['automation-drop-to-cdn']);
  expect(requirements).toHaveLength(1);
  expect(methodFromRequirement(requirements[0]).method_kind).toBe('api_key');
  expect(methodFromRequirement(requirements[0]).is_oauth).toBe(false);
});
