import { beforeAll, expect, it } from 'vitest';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { getNodeCredentialInfo, NODE_SCHEMAS, loadNodeSchemas } from '~/utils/nodeSchemas';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';

beforeAll(() => loadNodeSchemas(['automation-domainsdb']));
it('discovers the Domains-Index token as one manual API key method', () => {
  expect(getCredentialTypeFromSchemaTitle('DomainsdbAPIKeyCredential')).toBe('domainsdb_api_key');
  expect(getCredentialTypeFromSchemaTitle('Domains-Index API Key')).toBe('domainsdb_api_key');
  expect(getNodeCredentialInfo('automation-domainsdb')?.acceptedTypes).toEqual(['domainsdb_api_key']);
  const requirements = requirementsFromSchema(NODE_SCHEMAS['automation-domainsdb']);
  expect(requirements).toHaveLength(1);
  expect(methodFromRequirement(requirements[0]).method_kind).toBe('api_key');
  expect(methodFromRequirement(requirements[0]).is_oauth).toBe(false);
});
