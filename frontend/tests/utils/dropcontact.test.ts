// Exercise Dropcontact's generated schema, credential selection and editor controls.
import { beforeAll, describe, expect, it } from 'vitest';
import { loadNodeSchemas, getNodeSchema, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { upsertCredentialsIntoCache, removeCredentialsFromCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';
import { renderGenerationField } from '~/components/workflow/schemaFieldRenderer';
let schema: Record<string, any>;
beforeAll(async () => {
  await loadNodeSchemas(['automation-dropcontact']);
  schema = getNodeSchema('automation-dropcontact')!;
});
const operations = ['test_connection', 'get_credits', 'enrich_contact', 'enrich_batch', 'get_status', 'get_results'];
describe('native Dropcontact prepared contracts', () => {
  it('discovers native family, six closed operations and honest editor controls', () => {
    expect(getNodeSchema('automation-dropcontact')).toEqual(schema);
    expect(getNodeCredentialInfo('automation-dropcontact')?.acceptedTypes).toEqual(['dropcontact_access_token']);
    expect(CREDENTIAL_TYPE_MAP.DropcontactAccessTokenCredential).toBe('dropcontact_access_token');
    expect(humanizeCredentialLabel('DropcontactAccessToken')).toBe('Dropcontact Access Token');
    const defs = schema.$defs as Record<string, any>;
    expect(Object.values(defs).filter(d => d.properties?.operation?.const).map(d => d.properties.operation.const).sort()).toEqual([...operations].sort());
    expect(defs.DropcontactAccessTokenCredential.properties.access_token['ui:widget']).toBe('password');
    expect(defs.DropcontactAccessTokenCredential['x-credential-instructions']).toContain('X-Access-Token');
    expect(defs.DropcontactAccessTokenCredential).not.toHaveProperty('x-oauth-provider');
    expect(defs.DropcontactEnrichBatchConfig.properties.contacts_json['ui:widget']).toBe('textarea');
    expect(defs.DropcontactEnrichBatchConfig.additionalProperties).toBe(false);
    for (const key of ['custom_callback_url', 'forceResults', 'url', 'access_token']) expect(defs.DropcontactEnrichBatchConfig.properties).not.toHaveProperty(key);
    expect(defs.DropcontactEnrichContactConfig.properties.custom_fields_json['ui:widget']).toBe('textarea');
    expect(defs.DropcontactEnrichContactConfig.properties.language.enum).toEqual(['en', 'fr']);
    expect(defs.DropcontactEnrichContactConfig.properties.confirm_existing_credits.default).toBe(false);
    expect(defs.DropcontactEnrichBatchConfig.properties.confirm_existing_credits.default).toBe(false);
    expect(defs.DropcontactGetResultsConfig.properties.include_contact_data.default).toBe(false);
    expect(defs.DropcontactGetResultsConfig.properties.include_custom_fields.default).toBe(false);
    expect(defs.DropcontactGetResultsConfig.properties.expected_contact_count.anyOf).toEqual(expect.arrayContaining([expect.objectContaining({ type: 'integer', maximum: 250 })]));
  });
  it('selects current owned Dropcontact credentials', () => {
    const own = 'dropcontact-owned', foreign = 'dropcontact-foreign';
    try {
      upsertCredentialsIntoCache([{ id: own, name: 'Owned', credential_type: 'dropcontact_access_token', owned_by_me: true }, { id: foreign, name: 'Foreign', credential_type: 'dropcontact_access_token', owned_by_me: false }]);
      expect(autoSelectCredentialFromCache('automation-dropcontact')).toEqual({ dropcontact_access_token: own });
    } finally { removeCredentialsFromCache([own, foreign]); }
  });
  it('retains exact protected request scope without inventing history or polling', () => {
    const tools = getAgentToolOperations('automation-dropcontact');
    expect(tools.map(t => t.operation).sort()).toEqual([...operations].sort());
    for (const operation of ['get_results', 'get_status']) expect(tools.find(t => t.operation === operation)!.scopableFields).toEqual(expect.arrayContaining([expect.objectContaining({ field: 'request_id', resourceType: 'dropcontact_request' })]));
    const defs = schema.$defs as Record<string, any>;
    expect(defs.DropcontactGetResultsConfig.properties.request_id['x-dynamic-options'].allow_custom).toBe(true);
    expect(defs.DropcontactGetResultsConfig.properties.request_id.description).toContain('no documented history list');
    expect(defs.DropcontactCheckConfig.properties).not.toHaveProperty('contacts_json');
    for (const op of ['list_requests', 'poll', 'force_results', 'set_callback', 'set_webhook', 'cancel', 'delete_request', 'subscribe', 'mcp', 'arbitrary_request']) expect(operations).not.toContain(op);
  });
  it('passes JSON text unchanged through the actual generation form control', () => {
    const defs = schema.$defs as Record<string, any>;
    for (const [definition, field] of [['DropcontactEnrichBatchConfig', 'contacts_json'], ['DropcontactEnrichContactConfig', 'custom_fields_json']]) {
      const changes: Array<[string, unknown]> = [];
      const control = renderGenerationField({ fieldKey: field, fieldSchema: defs[definition].properties[field], value: '', onChange: (key, value) => changes.push([key, value]) })!;
      expect(control.type).toBe('textarea');
      const props = control.props as { value: string; onChange: (event: { target: { value: string } }) => void };
      expect(props.value).toBe('');
      for (const text of ['  ', '{"owned_ref":"private fixture"}', '[{"full_name":"Owned","company":"Owned"}]']) props.onChange({ target: { value: text } });
      expect(changes).toEqual(['  ', '{"owned_ref":"private fixture"}', '[{"full_name":"Owned","company":"Owned"}]'].map(value => [field, value]));
    }
  });
});
