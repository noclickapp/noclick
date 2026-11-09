import { beforeAll, expect, it } from 'vitest';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { getNodeCredentialInfo, NODE_SCHEMAS, loadNodeSchemas } from '~/utils/nodeSchemas';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';

beforeAll(() => loadNodeSchemas(['automation-unifi']));
it('discovers the UniFi token as one manual API key method', () => {
  expect(getCredentialTypeFromSchemaTitle('UnifiAPIKeyCredential')).toBe('unifi_api_key');
  expect(getCredentialTypeFromSchemaTitle('UniFi API Key')).toBe('unifi_api_key');
  expect(getNodeCredentialInfo('automation-unifi')?.acceptedTypes).toEqual(['unifi_api_key']);
  const requirements = requirementsFromSchema(NODE_SCHEMAS['automation-unifi']);
  expect(requirements).toHaveLength(1);
  expect(methodFromRequirement(requirements[0]).method_kind).toBe('api_key');
  expect(methodFromRequirement(requirements[0]).is_oauth).toBe(false);
});
