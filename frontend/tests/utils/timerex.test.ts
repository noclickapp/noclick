import { beforeAll, expect, it } from 'vitest';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { getNodeCredentialInfo, NODE_SCHEMAS, loadNodeSchemas } from '~/utils/nodeSchemas';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';

beforeAll(() => loadNodeSchemas(['automation-timerex']));
it('discovers the TimeRex key as a manual API key method', () => {
  expect(getCredentialTypeFromSchemaTitle('TimeRexAPIKeyCredential')).toBe('timerex_api_key');
  expect(getCredentialTypeFromSchemaTitle('TimeRex API Key')).toBe('timerex_api_key');
  expect(getNodeCredentialInfo('automation-timerex')?.acceptedTypes).toEqual(['timerex_api_key']);
  const requirements = requirementsFromSchema(NODE_SCHEMAS['automation-timerex']);
  expect(requirements).toHaveLength(1);
  expect(methodFromRequirement(requirements[0])).toMatchObject({ method_kind: 'api_key', is_oauth: false });
});
