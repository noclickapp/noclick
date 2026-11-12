import { beforeAll, expect, it } from 'vitest';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { getNodeCredentialInfo, NODE_SCHEMAS, loadNodeSchemas } from '~/utils/nodeSchemas';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';

beforeAll(() => loadNodeSchemas(['automation-wistia']));
it('discovers the Wistia token as one manual API key method', () => {
  expect(getCredentialTypeFromSchemaTitle('WistiaAPITokenCredential')).toBe('wistia_api_token');
  expect(getCredentialTypeFromSchemaTitle('Wistia API Token')).toBe('wistia_api_token');
  expect(getNodeCredentialInfo('automation-wistia')?.acceptedTypes).toEqual(['wistia_api_token', 'wistia_mcp']); // and its vendor's MCP server, last (backend nodes/core/vendor_mcp.py)
  const requirements = requirementsFromSchema(NODE_SCHEMAS['automation-wistia']);
  expect(requirements.map(r => r.credential_type)).toEqual(['wistia_api_token', 'wistia_mcp']);
  expect(methodFromRequirement(requirements[0]).method_kind).toBe('api_key');
  expect(methodFromRequirement(requirements[0]).is_oauth).toBe(false);
});
