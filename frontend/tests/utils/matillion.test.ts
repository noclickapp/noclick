import { beforeAll, describe, expect, it } from 'vitest';
import schema from '~/schemas/nodes/matillion.json';
import { loadNodeSchemas, getNodeSchema, getAgentToolOperations, getNodeCredentialInfo, filterConfigForExecution } from '~/utils/nodeSchemas';
import { upsertCredentialsIntoCache, removeCredentialsFromCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';

const operations = ['test_connection', 'list_projects', 'list_environments', 'list_published_pipelines', 'list_artifacts', 'get_artifact_metadata', 'list_pipeline_executions', 'get_pipeline_execution_metadata', 'get_pipeline_execution_status', 'list_execution_steps', 'list_execution_tasks', 'start_pipeline_execution', 'cancel_pipeline_execution', 'list_shared_artifact_metadata', 'get_shared_artifact_metadata'];

describe('Maia (Matillion) integration', () => {
  beforeAll(async () => { await loadNodeSchemas(['automation-matillion']); });
  it('discovers two issued credential families and exactly 15 typed operations', () => {
    expect(getNodeSchema('automation-matillion')).toEqual(schema);
    expect(getNodeCredentialInfo('automation-matillion')?.acceptedTypes.sort()).toEqual(['matillion_bearer_token', 'matillion_client_credentials']);
    expect(CREDENTIAL_TYPE_MAP.MatillionBearerTokenCredential).toBe('matillion_bearer_token');
    expect(CREDENTIAL_TYPE_MAP.MatillionClientCredentialsCredential).toBe('matillion_client_credentials');
    expect(humanizeCredentialLabel('MatillionBearerToken')).toBe('Matillion Bearer Token');
    const defs = schema.$defs as Record<string, any>;
    expect(Object.values(defs).filter(d => d.properties?.operation?.const).map(d => d.properties.operation.const).sort()).toEqual([...operations].sort());
    expect(defs.MatillionBearerTokenCredential.properties.access_token['ui:widget']).toBe('password');
    expect(defs.MatillionClientCredentialsCredential.properties.client_secret['ui:widget']).toBe('password');
    expect(defs.MatillionClientCredentialsCredential.properties.region.enum).toEqual(['eu1', 'us1', 'au1']);
    expect(defs.MatillionClientCredentialsCredential['x-credential-instructions']).toContain('client_credentials');
    expect(defs.MatillionClientCredentialsCredential).not.toHaveProperty('x-oauth-provider');
    expect(defs.MatillionStartConfig.properties.confirm_execution.default).toBe(false);
    expect(defs.MatillionCancelConfig.properties.force_termination.default).toBe(false);
  });

  it('uses typed credential forms for both methods', () => {
    const methods = requirementsFromSchema(schema).map(methodFromRequirement);
    expect(methods.map(method => method.method_kind)).toEqual(['api_key', 'api_key']);
    expect(methods.every(method => !method.is_oauth)).toBe(true);
  });

  it('auto-selects the preferred bearer family and retains explicit confirmation', () => {
    const bearer = 'matillion-owned-bearer', client = 'matillion-owned-client', foreign = 'matillion-foreign';
    try {
      upsertCredentialsIntoCache([
        { id: bearer, name: 'Owned bearer', credential_type: 'matillion_bearer_token', owned_by_me: true },
        { id: client, name: 'Owned client', credential_type: 'matillion_client_credentials', owned_by_me: true },
        { id: foreign, name: 'Foreign', credential_type: 'matillion_bearer_token', owned_by_me: false },
      ]);
      expect(autoSelectCredentialFromCache('automation-matillion')).toEqual({ matillion_bearer_token: bearer });
      removeCredentialsFromCache([bearer]);
      // Staging auto-selects only the schema's first family; clients use the form.
      expect(autoSelectCredentialFromCache('automation-matillion')).toEqual({});
      const cfg = filterConfigForExecution('automation-matillion', { operation: 'start_pipeline_execution', project_id: '00000000-0000-0000-0000-000000000001', environment_name: 'Dev', pipeline_name: 'Owned', confirm_execution: true });
      expect(cfg.confirm_execution).toBe(true);
      expect(schema.$defs.MatillionStartConfig.additionalProperties).toBe(false);
    } finally {
      removeCredentialsFromCache([bearer, client, foreign]);
    }
  });

  it('walks project/environment/pipeline/execution scopes through actual Agent metadata', () => {
    const defs = schema.$defs as Record<string, any>;
    expect(defs.MatillionStartConfig.properties.environment_name['x-dynamic-options'].depends_on).toBe('project_id');
    expect(defs.MatillionStartConfig.properties.pipeline_name['x-dynamic-options'].depends_on).toBe('environment_name');
    expect(defs.MatillionGetExecutionConfig.properties.pipeline_execution_id['x-dynamic-options'].depends_on).toBe('project_id');
    const tools = getAgentToolOperations('automation-matillion');
    expect(tools.map(t => t.operation).sort()).toEqual([...operations].sort());
    expect(tools.find(t => t.operation === 'cancel_pipeline_execution')!.scopableFields).toEqual(expect.arrayContaining([
      expect.objectContaining({ field: 'project_id', resourceType: 'matillion_project' }),
      expect.objectContaining({ field: 'pipeline_execution_id', resourceType: 'matillion_pipeline_execution', dependsOn: 'project_id' }),
    ]));
    for (const forbidden of ['arbitrary_request', 'create_ai_task', 'publish_artifact', 'create_schedule', 'create_connection', 'list_secrets', 'create_account']) expect(operations).not.toContain(forbidden);
  });
});
