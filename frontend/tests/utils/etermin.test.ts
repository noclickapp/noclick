import { beforeAll, expect, it } from 'vitest';
import { EterminNode } from '~/components/workflow/nodes/integrations/etermin';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { getNodeCredentialInfo, NODE_SCHEMAS, loadNodeSchemas, getAgentToolOperations } from '~/utils/nodeSchemas';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';

const type = 'automation-etermin';
beforeAll(() => loadNodeSchemas([type]));
it('discovers eTermin with one manual API key method and twenty operations', () => {
  expect(EterminNode.type).toBe(type);
  expect(EterminNode.label).toBe('eTermin');
  expect(getCredentialTypeFromSchemaTitle('EterminAPIKeyCredential')).toBe('etermin_api_key');
  expect(getCredentialTypeFromSchemaTitle('Etermin API Keys')).toBe('etermin_api_key');
  expect(getNodeCredentialInfo(type)?.acceptedTypes).toEqual(['etermin_api_key']);
  const requirements = requirementsFromSchema(NODE_SCHEMAS[type]);
  expect(requirements).toHaveLength(1);
  expect(methodFromRequirement(requirements[0]).method_kind).toBe('api_key');
  expect(methodFromRequirement(requirements[0]).is_oauth).toBe(false);
  expect(getAgentToolOperations(type)).toHaveLength(20);
});
