import { beforeAll, describe, expect, it } from 'vitest';
import schema from '~/schemas/nodes/statuspal.json';
import { loadNodeSchemas, getNodeSchema, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { upsertCredentialsIntoCache, removeCredentialsFromCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';
import { renderGenerationField } from '~/components/workflow/schemaFieldRenderer';
const operations = ['test_connection', 'list_status_pages', 'get_status_page', 'list_services', 'get_service'];
describe('StatusPal native reads', () => {
  beforeAll(async () => { await loadNodeSchemas(['automation-statuspal']); });
  it('discovers supplied raw API key, fixed region/org scope and five closed operations', () => {
    expect(getNodeSchema('automation-statuspal')).toEqual(schema);
    expect(getNodeCredentialInfo('automation-statuspal')?.acceptedTypes).toEqual(['statuspal_api_key']);
    expect(CREDENTIAL_TYPE_MAP.StatusPalAPIKeyCredential).toBe('statuspal_api_key');
    expect(humanizeCredentialLabel('StatusPalAPIKey')).toBe('Status Pal API Key');
    const defs = schema.$defs as Record<string, any>;
    expect(Object.values(defs).filter(d => d.properties?.operation?.const).map(d => d.properties.operation.const).sort()).toEqual([...operations].sort());
    expect(defs.StatusPalAPIKeyCredential.properties.api_key['ui:widget']).toBe('password');
    expect(defs.StatusPalAPIKeyCredential.properties.region.enum).toEqual(['us', 'eu']);
    expect(defs.StatusPalAPIKeyCredential.required).toContain('organization_id');
    expect(defs.StatusPalAPIKeyCredential['x-credential-instructions']).toContain('raw key, without Bearer');
    expect(defs.StatusPalAPIKeyCredential['x-credential-instructions']).toContain('reachability');
    expect(defs.StatusPalAPIKeyCredential).not.toHaveProperty('x-oauth-provider');
    expect(defs.StatusPalPagesConfig.properties.include_names.default).toBe(false);
    for (const field of ['url', 'page', 'cursor', 'page_token', 'per_page', 'notification_recipients']) expect(defs.StatusPalPagesConfig.properties).not.toHaveProperty(field);
    expect(defs.StatusPalServiceConfig.required).toEqual(expect.arrayContaining(['subdomain', 'service_id']));
  });
  it('selects the current owned native credential', () => {
    const own = 'statuspal-owned', foreign = 'statuspal-foreign';
    try {
      upsertCredentialsIntoCache([{ id: own, name: 'Owned', credential_type: 'statuspal_api_key', owned_by_me: true }, { id: foreign, name: 'Foreign', credential_type: 'statuspal_api_key', owned_by_me: false }]);
      expect(autoSelectCredentialFromCache('automation-statuspal')).toEqual({ statuspal_api_key: own });
    } finally { removeCredentialsFromCache([own, foreign]); }
  });
  it('exposes actual dependent service scope without controls', () => {
    const tools = getAgentToolOperations('automation-statuspal');
    expect(tools.map(t => t.operation).sort()).toEqual([...operations].sort());
    expect(tools.find(t => t.operation === 'get_service')!.scopableFields).toEqual(expect.arrayContaining([
      expect.objectContaining({ field: 'subdomain', resourceType: 'statuspal_status_page', loaderField: 'subdomain' }),
      expect.objectContaining({ field: 'service_id', resourceType: 'statuspal_service', loaderField: 'service_id', dependsOn: 'subdomain' }),
    ]));
    for (const op of ['summary', 'hello', 'create_incident', 'send_notification', 'push_metric', 'update_domain', 'create_api_key', 'arbitrary_request']) expect(operations).not.toContain(op);
  });
  it('uses actual supported numeric field callback and string picker dependency', () => {
    const defs = schema.$defs as Record<string, any>;
    expect(defs.StatusPalServiceConfig.properties.service_id['x-dynamic-options'].depends_on).toBe('subdomain');
    const changes: Array<[string, unknown]> = [];
    const element = renderGenerationField({ fieldKey: 'service_id', fieldSchema: defs.StatusPalServiceConfig.properties.service_id, value: '', onChange: (k, v) => changes.push([k, v]) })!;
    expect(element.type).toBe('input');
    const props = element.props as { type: string; onChange: (event: { target: { value: string } }) => void };
    expect(props.type).toBe('number'); props.onChange({ target: { value: '11' } }); props.onChange({ target: { value: '' } });
    expect(changes).toEqual([['service_id', 11], ['service_id', '']]);
  });
});
