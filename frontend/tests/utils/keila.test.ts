import { beforeAll, describe, expect, it } from 'vitest';
import { getNodeSchema, getNodeCredentialInfo, getAgentToolOperations, filterConfigForExecution, loadNodeSchemas } from '~/utils/nodeSchemas';
import { upsertCredentialsIntoCache, removeCredentialsFromCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';
import { renderGenerationField } from '~/components/workflow/schemaFieldRenderer';
const operations = ['test_connection', 'list_campaigns', 'get_campaign', 'list_templates', 'get_template'];
let schema: NonNullable<ReturnType<typeof getNodeSchema>>;
beforeAll(async () => {
  await loadNodeSchemas(['automation-keila']);
  schema = getNodeSchema('automation-keila')!;
});
describe('Keila project-context metadata reads', () => {
  it('discovers existing private keys and five closed operations', () => {
    expect(schema).toBeDefined();
    expect(getNodeCredentialInfo('automation-keila')?.acceptedTypes).toEqual(['keila_api_key']);
    expect(CREDENTIAL_TYPE_MAP.KeilaAPIKeyCredential).toBe('keila_api_key');
    expect(humanizeCredentialLabel('KeilaAPIKey')).toBe('Keila API Key');
    const defs = schema.$defs as Record<string, any>;
    expect(Object.values(defs).filter(d => d.properties?.operation?.const).map(d => d.properties.operation.const).sort()).toEqual([...operations].sort());
    expect(defs.KeilaAPIKeyCredential.properties.api_key['ui:widget']).toBe('password');
    expect(defs.KeilaAPIKeyCredential.required).toEqual(expect.arrayContaining(['api_key', 'instance_origin']));
    expect(defs.KeilaAPIKeyCredential).not.toHaveProperty('x-oauth-provider');
    expect(defs.KeilaTemplatesConfig.properties.include_names.default).toBe(false);
    expect(defs.KeilaTemplateConfig.properties.include_names.default).toBe(false);
    expect(defs.KeilaCampaignsConfig.properties).not.toHaveProperty('include_names');
    expect(defs.KeilaTemplateConfig.properties.template_id['x-dynamic-options']).not.toHaveProperty('depends_on');
    for (const field of ['url', 'page', 'per_page', 'page_token', 'project_id', 'subject', 'body']) expect(defs.KeilaCampaignsConfig.properties).not.toHaveProperty(field);
  });
  it('selects its native credential and filters unrelated operation fields', () => {
    const own = 'keila-owned', foreign = 'keila-foreign';
    try {
      upsertCredentialsIntoCache([{ id: own, name: 'Owned', credential_type: 'keila_api_key', owned_by_me: true }, { id: foreign, name: 'Foreign', credential_type: 'keila_api_key', owned_by_me: false }]);
      expect(autoSelectCredentialFromCache('automation-keila')).toEqual({ keila_api_key: own });
      expect(filterConfigForExecution('automation-keila', { operation: 'get_template', template_id: 'template-a', campaign_id: 'invented' })).toEqual({ operation: 'get_template', template_id: 'template-a' });
    } finally { removeCredentialsFromCache([own, foreign]); }
  });
  it('exposes independent real campaign and template Agent scopes', () => {
    const tools = getAgentToolOperations('automation-keila');
    expect(tools.map(t => t.operation).sort()).toEqual([...operations].sort());
    expect(tools.find(t => t.operation === 'get_campaign')!.scopableFields).toEqual([expect.objectContaining({ field: 'campaign_id', resourceType: 'keila_campaign', loaderField: 'campaign_id' })]);
    expect(tools.find(t => t.operation === 'get_template')!.scopableFields).toEqual([expect.objectContaining({ field: 'template_id', resourceType: 'keila_template', loaderField: 'template_id' })]);
    for (const op of ['get_me', 'send_campaign', 'create_campaign', 'render_template', 'list_contacts', 'arbitrary_request']) expect(operations).not.toContain(op);
  });
  it('uses the actual numeric editor for the local output cap', () => {
    const defs = schema.$defs as Record<string, any>;
    expect(defs.KeilaTemplatesConfig.properties.output_limit.maximum).toBe(100);
    const changes: Array<[string, unknown]> = [];
    const element = renderGenerationField({ fieldKey: 'output_limit', fieldSchema: defs.KeilaTemplatesConfig.properties.output_limit, value: 100, onChange: (k, v) => changes.push([k, v]) })!;
    expect(element.type).toBe('input');
    const props = element.props as { type: string; onChange: (event: { target: { value: string } }) => void };
    expect(props.type).toBe('number'); props.onChange({ target: { value: '20' } });
    expect(changes).toEqual([['output_limit', 20]]);
  });
});
