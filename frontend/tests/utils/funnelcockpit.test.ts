import { beforeAll, expect, it } from 'vitest';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { getNodeCredentialInfo, NODE_SCHEMAS, loadNodeSchemas } from '~/utils/nodeSchemas';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';
import { FunnelCockpitNode } from '~/components/workflow/nodes/integrations/funnelcockpit';

beforeAll(() => loadNodeSchemas(['automation-funnelcockpit']));
it('discovers FunnelCockpit and its manually entered private API key', () => {
  expect(FunnelCockpitNode.type).toBe('automation-funnelcockpit');
  expect(FunnelCockpitNode.category).toBe('marketing');
  expect(getCredentialTypeFromSchemaTitle('FunnelCockpitAPIKeyCredential')).toBe('funnelcockpit_api_key');
  expect(getCredentialTypeFromSchemaTitle('FunnelCockpit API Key')).toBe('funnelcockpit_api_key');
  expect(getNodeCredentialInfo('automation-funnelcockpit')?.acceptedTypes).toEqual(['funnelcockpit_api_key']);
  const requirements = requirementsFromSchema(NODE_SCHEMAS['automation-funnelcockpit']);
  expect(requirements).toHaveLength(1);
  expect(methodFromRequirement(requirements[0]).method_kind).toBe('api_key');
  expect(methodFromRequirement(requirements[0]).is_oauth).toBe(false);
});
