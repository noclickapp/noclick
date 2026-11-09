import { beforeAll, expect, it } from 'vitest';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { getNodeCredentialInfo, NODE_SCHEMAS, loadNodeSchemas } from '~/utils/nodeSchemas';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';

beforeAll(() => loadNodeSchemas(['automation-proxiedmail']));
it('discovers the ProxiedMail token as one manual API key method', () => {
  expect(getCredentialTypeFromSchemaTitle('ProxiedmailAPITokenCredential')).toBe('proxiedmail_api_token');
  expect(getCredentialTypeFromSchemaTitle('Proxiedmail API Token')).toBe('proxiedmail_api_token');
  expect(getNodeCredentialInfo('automation-proxiedmail')?.acceptedTypes).toEqual(['proxiedmail_api_token']);
  const requirements = requirementsFromSchema(NODE_SCHEMAS['automation-proxiedmail']);
  expect(requirements).toHaveLength(1);
  expect(methodFromRequirement(requirements[0]).method_kind).toBe('api_key');
  expect(methodFromRequirement(requirements[0]).is_oauth).toBe(false);
});
