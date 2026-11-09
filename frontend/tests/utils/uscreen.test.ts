import { beforeAll, expect, it } from 'vitest';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { getNodeCredentialInfo, NODE_SCHEMAS, loadNodeSchemas } from '~/utils/nodeSchemas';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';

beforeAll(() => loadNodeSchemas(['automation-uscreen']));
it('discovers the Uscreen token as one manual API key method', () => {
  expect(getCredentialTypeFromSchemaTitle('UscreenAPIKeyCredential')).toBe('uscreen_api_key');
  expect(getCredentialTypeFromSchemaTitle('Uscreen API Key')).toBe('uscreen_api_key');
  expect(getNodeCredentialInfo('automation-uscreen')?.acceptedTypes).toEqual(['uscreen_api_key']);
  const requirements = requirementsFromSchema(NODE_SCHEMAS['automation-uscreen']);
  expect(requirements).toHaveLength(1);
  expect(methodFromRequirement(requirements[0]).method_kind).toBe('api_key');
  expect(methodFromRequirement(requirements[0]).is_oauth).toBe(false);
});
