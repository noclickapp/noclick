import { beforeAll, describe, expect, it } from 'vitest';
import schema from '~/schemas/nodes/goatcounter.json';
import { loadNodeSchemas, getNodeSchema, getNodeCredentialInfo, getAgentToolOperations, filterConfigForExecution } from '~/utils/nodeSchemas';
import { upsertCredentialsIntoCache, removeCredentialsFromCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';
import { renderGenerationField } from '~/components/workflow/schemaFieldRenderer';
const operations = ['test_connection', 'list_sites', 'get_site', 'get_total_counts', 'get_hits_counts'];
describe('GoatCounter fixed-origin metadata/count node', () => {
  beforeAll(async () => { await loadNodeSchemas(['automation-goatcounter']); });
  it('discovers the supplied token and five closed operations', () => {
    expect(getNodeSchema('automation-goatcounter')).toEqual(schema);
    expect(getNodeCredentialInfo('automation-goatcounter')?.acceptedTypes).toEqual(['goatcounter_api_token']);
    expect(CREDENTIAL_TYPE_MAP.GoatCounterAPITokenCredential).toBe('goatcounter_api_token');
    expect(humanizeCredentialLabel('GoatCounterAPIToken')).toBe('Goat Counter API Token');
    const defs = schema.$defs as Record<string, any>;
    expect(Object.values(defs).filter(d => d.properties?.operation?.const).map(d => d.properties.operation.const).sort()).toEqual([...operations].sort());
    expect(defs.GoatCounterAPITokenCredential.properties.api_token['ui:widget']).toBe('password');
    expect(defs.GoatCounterAPITokenCredential.required).toEqual(expect.arrayContaining(['api_token', 'site_origin', 'site_id']));
    expect(defs.GoatCounterAPITokenCredential).not.toHaveProperty('x-oauth-provider');
    expect(defs.GoatCounterHitsConfig.properties.limit.maximum).toBe(100);
    expect(defs.GoatCounterHitsConfig.properties.limit.default).toBe(20);
    expect(defs.GoatCounterHitsConfig.properties.include_path_details.default).toBe(false);
    expect(defs.GoatCounterSitesConfig.properties.include_names.default).toBe(false);
    for (const field of ['url', 'group', 'daily', 'path_by_name', 'user', 'token', 'page_token']) expect(defs.GoatCounterHitsConfig.properties).not.toHaveProperty(field);
    expect(defs.GoatCounterTotalsConfig.properties).not.toHaveProperty('exclude_paths');
  });
  it('uses both native selectors and filters unrelated execution fields', () => {
    const own = 'goatcounter-owned', foreign = 'goatcounter-foreign';
    try {
      upsertCredentialsIntoCache([{ id: own, name: 'Owned', credential_type: 'goatcounter_api_token', owned_by_me: true }, { id: foreign, name: 'Foreign', credential_type: 'goatcounter_api_token', owned_by_me: false }]);
      expect(autoSelectCredentialFromCache('automation-goatcounter')).toEqual({ goatcounter_api_token: own });
      expect(filterConfigForExecution('automation-goatcounter', { operation: 'get_site', site_id: 7, limit: 20, exclude_paths: ['13'] })).toEqual({ operation: 'get_site', site_id: 7 });
    } finally { removeCredentialsFromCache([own, foreign]); }
  });
  it('exposes only real current site scopes without user/token/control routes', () => {
    const tools = getAgentToolOperations('automation-goatcounter');
    expect(tools.map(t => t.operation).sort()).toEqual([...operations].sort());
    for (const operation of ['get_site', 'get_total_counts', 'get_hits_counts']) expect(tools.find(t => t.operation === operation)!.scopableFields).toEqual([expect.objectContaining({ field: 'site_id', resourceType: 'goatcounter_site', loaderField: 'site_id' })]);
    for (const op of ['get_me', 'export', 'download', 'count', 'update_site', 'create_token', 'arbitrary_request']) expect(operations).not.toContain(op);
  });
  it('uses actual numeric and registered string-list editor callbacks', () => {
    const defs = schema.$defs as Record<string, any>;
    const changes: Array<[string, unknown]> = [];
    const element = renderGenerationField({ fieldKey: 'limit', fieldSchema: defs.GoatCounterHitsConfig.properties.limit, value: 20, onChange: (k, v) => changes.push([k, v]) })!;
    expect(element.type).toBe('input');
    const props = element.props as { type: string; onChange: (event: { target: { value: string } }) => void };
    expect(props.type).toBe('number'); props.onChange({ target: { value: '20' } });
    expect(changes).toEqual([['limit', 20]]);
    for (const field of ['include_paths', 'exclude_paths']) {
      expect(defs.GoatCounterHitsConfig.properties[field]['ui:widget']).toBe('list');
      const list = renderGenerationField({ fieldKey: field, fieldSchema: defs.GoatCounterHitsConfig.properties[field], value: [], onChange: (k, v) => changes.push([k, v]) })!;
      expect(list).not.toBeNull();
      (list.props as { onChange: (ids: string[]) => void }).onChange(['13', '14']);
      expect(changes.at(-1)).toEqual([field, ['13', '14']]);
    }
  });
});
