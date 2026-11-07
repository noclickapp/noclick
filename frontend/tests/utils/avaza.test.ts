import { beforeAll, describe, expect, it } from 'vitest';
import schema from '~/schemas/nodes/avaza.json';
import { loadNodeSchemas, getNodeSchema, getNodeCredentialInfo, getAgentToolOperations, filterConfigForExecution } from '~/utils/nodeSchemas';
import { upsertCredentialsIntoCache, removeCredentialsFromCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';
import { renderGenerationField } from '~/components/workflow/schemaFieldRenderer';

const operations = ['test_connection', 'get_account', 'list_companies', 'get_company', 'list_projects', 'get_project', 'list_project_team', 'list_tasks', 'get_task', 'list_time_entries', 'get_time_entry'];
describe('Avaza native contracts', () => {
  beforeAll(async () => { await loadNodeSchemas(['automation-avaza']); });
  it('discovers one supplied Bearer access token and eleven closed read operations', () => {
    expect(getNodeSchema('automation-avaza')).toEqual(schema);
    expect(getNodeCredentialInfo('automation-avaza')?.acceptedTypes).toEqual(['avaza_access_token']);
    expect(CREDENTIAL_TYPE_MAP.AvazaAccessTokenCredential).toBe('avaza_access_token');
    expect(humanizeCredentialLabel('AvazaAccessToken')).toBe('Avaza Access Token');
    const defs = schema.$defs as Record<string, any>;
    expect(Object.values(defs).filter(d => d.properties?.operation?.const).map(d => d.properties.operation.const).sort()).toEqual([...operations].sort());
    expect(defs.AvazaAccessTokenCredential.properties.access_token['ui:widget']).toBe('password');
    expect(defs.AvazaAccessTokenCredential.properties.token_source.enum).toEqual(['personal_access_token', 'oauth2_access_token']);
    expect(defs.AvazaAccessTokenCredential['x-credential-instructions']).toContain('Authorization: Bearer');
    expect(defs.AvazaAccessTokenCredential['x-credential-instructions']).toContain('actual AccountID');
    expect(defs.AvazaAccessTokenCredential).not.toHaveProperty('x-oauth-provider');
    expect(defs.AvazaCompaniesConfig.properties.page_size.default).toBe(20);
    expect(defs.AvazaCompaniesConfig.properties.page_size.maximum).toBe(1000);
    expect(defs.AvazaTaskConfig.properties.include_names.default).toBe(false);
    expect(defs.AvazaTeamConfig.properties.include_names.default).toBe(false);
    expect(defs.AvazaTimesheetsConfig.properties).not.toHaveProperty('is_complete');
    expect(defs.AvazaTimesheetsConfig.required).toEqual(expect.arrayContaining(['account_id', 'company_id', 'project_id', 'entry_date_from', 'entry_date_to']));
  });
  it('uses current owned cache selections and forwards native config', () => {
    const own = 'avaza-owned', foreign = 'avaza-foreign';
    try {
      upsertCredentialsIntoCache([{ id: own, name: 'Owned', credential_type: 'avaza_access_token', owned_by_me: true }, { id: foreign, name: 'Foreign', credential_type: 'avaza_access_token', owned_by_me: false }]);
      expect(autoSelectCredentialFromCache('automation-avaza')).toEqual({ avaza_access_token: own });
      // Staging forwards config; the backend's extra='forbid' models enforce the closed operation.
      const cfg = filterConfigForExecution('automation-avaza', { operation: 'get_task', account_id: 7, company_id: 11, project_id: 22, task_id: 33, include_names: false });
      expect(cfg).toEqual({ operation: 'get_task', account_id: 7, company_id: 11, project_id: 22, task_id: 33, include_names: false });
    } finally { removeCredentialsFromCache([own, foreign]); }
  });
  it('exposes account/company/project/task ancestry and manual time IDs', () => {
    const tools = getAgentToolOperations('automation-avaza');
    expect(tools.map(t => t.operation).sort()).toEqual([...operations].sort());
    expect(tools.find(t => t.operation === 'get_task')!.scopableFields).toEqual(expect.arrayContaining([
      expect.objectContaining({ field: 'account_id', resourceType: 'avaza_account', loaderField: 'account_id' }),
      expect.objectContaining({ field: 'company_id', resourceType: 'avaza_company', loaderField: 'company_id', dependsOn: 'account_id' }),
      expect.objectContaining({ field: 'project_id', resourceType: 'avaza_project', loaderField: 'project_id', dependsOn: 'company_id' }),
      expect.objectContaining({ field: 'task_id', resourceType: 'avaza_task', loaderField: 'task_id', dependsOn: 'project_id' }),
    ]));
    expect(tools.find(t => t.operation === 'get_time_entry')!.scopableFields.map(f => f.field)).not.toContain('time_entry_id');
    for (const op of ['approve_timesheet', 'send_invite', 'write_task', 'get_invoice', 'whoami', 'arbitrary_request', 'refresh_token']) expect(operations).not.toContain(op);
  });
  it('uses supported numeric generation callbacks and single-string picker dependencies', () => {
    const defs = schema.$defs as Record<string, any>;
    expect(defs.AvazaTaskConfig.properties.task_id['x-dynamic-options'].depends_on).toBe('project_id');
    expect(defs.AvazaProjectConfig.properties.project_id['x-dynamic-options'].depends_on).toBe('company_id');
    const changes: Array<[string, unknown]> = [];
    for (const [key, field, value] of [['page_size', defs.AvazaCompaniesConfig.properties.page_size, '20'], ['time_entry_id', defs.AvazaTimesheetConfig.properties.time_entry_id, '44']] as const) {
      const element = renderGenerationField({ fieldKey: key, fieldSchema: field, value: '', onChange: (k, v) => changes.push([k, v]) })!;
      expect(element.type).toBe('input');
      const props = element.props as { type: string; onChange: (event: { target: { value: string } }) => void };
      expect(props.type).toBe('number'); props.onChange({ target: { value } }); props.onChange({ target: { value: '' } });
    }
    expect(changes).toEqual([['page_size', 20], ['page_size', ''], ['time_entry_id', 44], ['time_entry_id', '']]);
  });
});
