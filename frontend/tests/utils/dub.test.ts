import { beforeAll, describe, expect, it } from 'vitest';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { getNodeCredentialInfo, NODE_SCHEMAS, loadNodeSchemas, filterConfigForExecution } from '~/utils/nodeSchemas';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';

describe('Dub native metadata integration', () => {
  beforeAll(() => loadNodeSchemas(['automation-dub']));
  it('discovers the workspace API key as a single API key method', () => {
    expect(getCredentialTypeFromSchemaTitle('DubApiKeyCredential')).toBe('dub_api_key');
    expect(getCredentialTypeFromSchemaTitle('Dub Workspace API Key')).toBe('dub_api_key');
    expect(getNodeCredentialInfo('automation-dub')?.acceptedTypes).toEqual(['dub_api_key']);
    const requirements = requirementsFromSchema(NODE_SCHEMAS['automation-dub']);
    expect(requirements).toHaveLength(1);
    expect(methodFromRequirement(requirements[0]).method_kind).toBe('api_key');
    expect(methodFromRequirement(requirements[0]).is_oauth).toBe(false);
  });
  it('keeps link selection bound to its domain and exposes only read operations', () => {
    const schema = NODE_SCHEMAS['automation-dub'];
    const defs = schema.$defs;
    expect(defs.DubLinkConfig.properties.link_id['x-dynamic-options'].depends_on).toContain('domain_id');
    expect(defs.DubLinkConfig.properties.domain_id['x-resource-type']).toBe('domain_id');
    expect(defs.DubLinkConfig.properties.starting_after.anyOf).toContainEqual({ type: 'string', maxLength: 255 });
    expect(defs.DubLinkConfig.properties.page).toBeUndefined();
    const ops = ['DubDomainsConfig', 'DubLinksConfig', 'DubLinkConfig', 'DubCountConfig'].map(key => defs[key].properties.operation.const);
    expect(ops.sort()).toEqual(['count_links', 'get_link', 'list_domains', 'list_links']);
    expect(schema['x-agent-tool-provider']).toBe(true);
    expect(defs.DubLinksConfig.allOf).toEqual([{ anyOf: [
      { properties: { starting_after: { const: null } } },
      { properties: { ending_before: { const: null } } },
    ] }]);
    expect(filterConfigForExecution('automation-dub', {
      operation: 'list_links', domain_id: 'domain_a', starting_after: 'link_a', ending_before: null, link_id: 'discard',
    })).toEqual({ operation: 'list_links', domain_id: 'domain_a', starting_after: 'link_a', ending_before: null });
  });
});
