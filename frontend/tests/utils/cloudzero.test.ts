// Prepared UNRUN: separate native generation and frontend lane are required.
import { beforeAll, describe, expect, it } from 'vitest';
import schema from '~/schemas/nodes/cloudzero.json';
import { loadNodeSchemas, getNodeSchema, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { upsertCredentialsIntoCache, removeCredentialsFromCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';
import { renderGenerationField } from '~/components/workflow/schemaFieldRenderer';

beforeAll(async () => { await loadNodeSchemas(['automation-cloudzero']); });

const operations = ['test_connection', 'list_dimensions', 'get_dimension', 'get_costs', 'list_views', 'get_view'];
describe('native CloudZero prepared contracts', () => {
  it('discovers the existing key and six read-only operations with honest scopes', () => {
    expect(getNodeSchema('automation-cloudzero')).toEqual(schema);
    expect(getNodeCredentialInfo('automation-cloudzero')?.acceptedTypes).toEqual(['cloudzero_api_key']);
    expect(CREDENTIAL_TYPE_MAP.CloudZeroAPIKeyCredential).toBe('cloudzero_api_key');
    expect(humanizeCredentialLabel('CloudZeroAPIKey')).toBe('Cloud Zero API Key');
    const defs = schema.$defs as Record<string, any>;
    expect(Object.values(defs).filter(d => d.properties?.operation?.const).map(d => d.properties.operation.const).sort()).toEqual([...operations].sort());
    expect(defs.CloudZeroAPIKeyCredential.properties.api_key['ui:widget']).toBe('password');
    expect(defs.CloudZeroAPIKeyCredential['x-credential-instructions']).toContain('without Bearer');
    expect(defs.CloudZeroAPIKeyCredential['x-credential-instructions']).toContain('billing:read_costs');
    expect(defs.CloudZeroAPIKeyCredential).not.toHaveProperty('x-oauth-provider');
    expect(defs.CloudZeroDimensionsConfig.properties.include_hidden.default).toBe(false);
    expect(defs.CloudZeroCostsConfig.properties.confirm_query_quota.default).toBe(false);
    expect(defs.CloudZeroCostsConfig.properties.group_by['ui:widget']).toBe('list');
    expect(defs.CloudZeroCostsConfig.properties.group_by.default).toEqual([]);
    expect(defs.CloudZeroCostsConfig.properties.filters_json['ui:widget']).toBe('textarea');
    expect(defs.CloudZeroCostsConfig.properties.cost_type.enum).toContain('usage_amount');
    expect(defs.CloudZeroViewConfig.properties.include_filters.default).toBe(false);
  });
  it('uses owned current selections', () => {
    const own = 'cloudzero-owned', foreign = 'cloudzero-foreign';
    try {
      upsertCredentialsIntoCache([{ id: own, name: 'Owned', credential_type: 'cloudzero_api_key', owned_by_me: true }, { id: foreign, name: 'Foreign', credential_type: 'cloudzero_api_key', owned_by_me: false }]);
      expect(autoSelectCredentialFromCache('automation-cloudzero')).toEqual({ cloudzero_api_key: own });
    } finally { removeCredentialsFromCache([own, foreign]); }
  });
  it('exposes genuine protected dimension/view scope without send or billing mutation', () => {
    const tools = getAgentToolOperations('automation-cloudzero');
    expect(tools.map(t => t.operation).sort()).toEqual([...operations].sort());
    expect(tools.find(t => t.operation === 'get_dimension')!.scopableFields).toEqual(expect.arrayContaining([expect.objectContaining({ field: 'dimension_id', resourceType: 'cloudzero_dimension' })]));
    expect(tools.find(t => t.operation === 'get_view')!.scopableFields).toEqual(expect.arrayContaining([expect.objectContaining({ field: 'view_id', resourceType: 'cloudzero_view' })]));
    for (const op of ['send_telemetry', 'create_view', 'publish_costformation', 'create_key', 'create_connection', 'set_budget', 'whoami', 'arbitrary_request']) expect(operations).not.toContain(op);
  });
  it('uses real numeric and JSON textarea generation callbacks', () => {
    const defs = schema.$defs as Record<string, any>, changes: Array<[string, unknown]> = [];
    const numeric = renderGenerationField({ fieldKey: 'limit', fieldSchema: defs.CloudZeroViewsConfig.properties.limit, value: 100, onChange: (key, value) => changes.push([key, value]) })!;
    expect(numeric.type).toBe('input');
    const np = numeric.props as { type: string; onChange: (event: { target: { value: string } }) => void };
    expect(np.type).toBe('number'); np.onChange({ target: { value: '2' } }); np.onChange({ target: { value: '' } });
    const text = renderGenerationField({ fieldKey: 'filters_json', fieldSchema: defs.CloudZeroCostsConfig.properties.filters_json, value: '', onChange: (key, value) => changes.push([key, value]) })!;
    expect(text.type).toBe('textarea');
    (text.props as { onChange: (event: { target: { value: string } }) => void }).onChange({ target: { value: '{"!Account":["owned"]}' } });
    expect(changes).toEqual([['limit', 2], ['limit', ''], ['filters_json', '{"!Account":["owned"]}']]);
  });
});
