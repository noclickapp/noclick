// Prepared UNRUN: native generation and a separate frontend lane are required.
import { describe, expect, it } from 'vitest';
import schema from '~/schemas/nodes/mediasilo.json';
import { getNodeSchema, getNodeCredentialInfo, getAgentToolOperations, filterConfigForExecution } from '~/utils/nodeSchemas';
import { autoSelectCredentialFromCache, upsertCredentialsIntoCache, removeCredentialsFromCache } from '~/utils/credentialAutoSelect';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';
import { renderGenerationField } from '~/components/workflow/schemaFieldRenderer';
const operations = ['test_connection', 'list_projects', 'get_project', 'list_folders', 'get_folder'];
describe('MediaSilo prepared native project/folder reads', () => {
  it('discovers both supplied password fields and five closed operations', () => {
    expect(getNodeSchema('automation-mediasilo')).toEqual(schema);
    expect(getNodeCredentialInfo('automation-mediasilo')?.acceptedTypes).toEqual(['mediasilo_api_key']);
    expect(CREDENTIAL_TYPE_MAP.MediaSiloAPIKeyCredential).toBe('mediasilo_api_key');
    expect(humanizeCredentialLabel('MediaSiloAPIKey')).toBe('MediaSilo API Key');
    const defs = schema.$defs as Record<string, any>;
    expect(Object.values(defs).filter(d => d.properties?.operation?.const).map(d => d.properties.operation.const).sort()).toEqual([...operations].sort());
    for (const field of ['api_key', 'api_secret']) {
      expect(defs.MediaSiloAPIKeyCredential.properties[field]['ui:widget']).toBe('password');
      expect(defs.MediaSiloAPIKeyCredential.required).toContain(field);
    }
    expect(defs.MediaSiloAPIKeyCredential['x-credential-instructions']).toContain('api.mediasilo.com');
    expect(defs.MediaSiloAPIKeyCredential['x-credential-instructions']).toContain('api.shift.io');
    expect(defs.MediaSiloAPIKeyCredential).not.toHaveProperty('x-oauth-provider');
    expect(defs.MediaSiloProjectsConfig.properties.include_names.default).toBe(false);
    for (const field of ['url', 'page', 'cursor', 'page_token', 'asset_id', 'download', 'owner']) expect(defs.MediaSiloProjectsConfig.properties).not.toHaveProperty(field);
    expect(defs.MediaSiloFolderConfig.required).toEqual(expect.arrayContaining(['project_id', 'folder_id']));
  });
  it('uses current owned native cache and strips unrelated execution fields', () => {
    const own = 'mediasilo-owned', foreign = 'mediasilo-foreign';
    try {
      upsertCredentialsIntoCache([{ id: own, name: 'Owned', credential_type: 'mediasilo_api_key', owned_by_me: true }, { id: foreign, name: 'Foreign', credential_type: 'mediasilo_api_key', owned_by_me: false }]);
      expect(autoSelectCredentialFromCache('automation-mediasilo')).toEqual({ mediasilo_api_key: own });
      expect(filterConfigForExecution('automation-mediasilo', { operation: 'get_folder', project_id: 'project-1', folder_id: 'folder-1', method: 'POST', api_secret: 'omit', url: 'https://evil.test', cursor: 'opaque', publish: true })).toEqual({ operation: 'get_folder', project_id: 'project-1', folder_id: 'folder-1' });
    } finally { removeCredentialsFromCache([own, foreign]); }
  });
  it('exposes actual parent-bound folder scope without media/control operations', () => {
    const tools = getAgentToolOperations('automation-mediasilo');
    expect(tools.map(t => t.operation).sort()).toEqual([...operations].sort());
    expect(tools.find(t => t.operation === 'get_folder')!.scopableFields).toEqual(expect.arrayContaining([
      expect.objectContaining({ field: 'project_id', resourceType: 'mediasilo_project', loaderField: 'project_id' }),
      expect.objectContaining({ field: 'folder_id', resourceType: 'mediasilo_folder', loaderField: 'folder_id', dependsOn: 'project_id' }),
    ]));
    for (const op of ['get_asset', 'download', 'create_project', 'upload', 'publish', 'create_key', 'arbitrary_request']) expect(operations).not.toContain(op);
  });
  it('uses supported string editor callback and exact folder dependency', () => {
    const defs = schema.$defs as Record<string, any>;
    expect(defs.MediaSiloFolderConfig.properties.folder_id['x-dynamic-options'].depends_on).toBe('project_id');
    const changes: Array<[string, unknown]> = [];
    const element = renderGenerationField({ fieldKey: 'folder_id', fieldSchema: defs.MediaSiloFolderConfig.properties.folder_id, value: '', onChange: (k, v) => changes.push([k, v]) })!;
    expect(element.type).toBe('input');
    const props = element.props as { type: string; onChange: (event: { target: { value: string } }) => void };
    expect(props.type).toBe('text'); props.onChange({ target: { value: 'folder-1' } }); props.onChange({ target: { value: '' } });
    expect(changes).toEqual([['folder_id', 'folder-1'], ['folder_id', '']]);
  });
});
