// ProductPlan schema, scoped metadata and current staging helper assertions.
import { beforeAll, describe, expect, it } from 'vitest';
import schema from '~/schemas/nodes/productplan.json';
import { loadNodeSchemas, getNodeSchema, getAgentToolOperations, getNodeCredentialInfo, filterConfigForExecution } from '~/utils/nodeSchemas';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';

const operations = ['test_connection', 'list_roadmaps', 'get_roadmap', 'list_roadmap_bars', 'get_bar', 'create_bar', 'update_bar', 'delete_bar', 'list_objectives', 'get_objective', 'list_key_results', 'get_key_result', 'list_ideas', 'get_idea', 'list_launches', 'get_launch', 'list_launch_tasks', 'list_teams'];

describe('native ProductPlan preparation', () => {
  beforeAll(() => loadNodeSchemas(['automation-productplan']));
  it('discovers the issued PAT and exactly 18 typed operations', () => {
    expect(getNodeSchema('automation-productplan')).toEqual(schema);
    expect(getNodeCredentialInfo('automation-productplan')?.acceptedTypes).toEqual(['productplan_pat']);
    expect(CREDENTIAL_TYPE_MAP.ProductPlanPATCredential).toBe('productplan_pat');
    const defs = schema.$defs as Record<string, any>;
    expect(Object.values(defs).filter(d => d.properties?.operation?.const).map(d => d.properties.operation.const).sort()).toEqual([...operations].sort());
    expect(defs.ProductPlanPATCredential.properties.personal_access_token['ui:widget']).toBe('password');
    expect(defs.ProductPlanPATCredential['x-credential-instructions']).toContain('Bearer TOKEN');
    expect(defs.ProductPlanCreateBarConfig.properties.tags['ui:widget']).toBe('list');
    expect(defs.ProductPlanCreateBarConfig.properties.tags.type).toBe('array');
    expect(defs.ProductPlanUpdateBarConfig.properties.description['ui:widget']).toBe('textarea');
    expect(defs.ProductPlanUpdateBarConfig.properties.description_mode.default).toBe('keep');
  });

  it('preserves deliberate clear modes and removes fields belonging to other operations', () => {
    const cfg = filterConfigForExecution('automation-productplan', { operation: 'update_bar', roadmap_id: 1, bar_id: 2, confirm_mutation: true, description_mode: 'clear', tags_mode: 'clear', name: 'old create name', starts_on: '2026-10-06', search: 'old search' });
    expect(cfg.description_mode).toBe('clear');
    expect(cfg.tags_mode).toBe('clear');
    for (const key of ['name', 'starts_on', 'search']) expect(cfg).not.toHaveProperty(key);
  });

  it('binds bar and key-result scopes through the actual Agent metadata walker', () => {
    const defs = schema.$defs as Record<string, any>;
    expect(defs.ProductPlanGetBarConfig.properties.bar_id['x-dynamic-options'].depends_on).toBe('roadmap_id');
    expect(defs.ProductPlanGetKeyResultConfig.properties.key_result_id['x-dynamic-options'].depends_on).toBe('objective_id');
    const tools = getAgentToolOperations('automation-productplan');
    expect(tools.map(t => t.operation).sort()).toEqual([...operations].sort());
    expect(tools.find(t => t.operation === 'delete_bar')!.scopableFields).toEqual(expect.arrayContaining([
      expect.objectContaining({ field: 'roadmap_id', resourceType: 'productplan_roadmap' }),
      expect.objectContaining({ field: 'bar_id', resourceType: 'productplan_bar', dependsOn: 'roadmap_id' }),
    ]));
    for (const forbidden of ['arbitrary_request', 'unpark_bar', 'share_roadmap', 'invite_user', 'create_token', 'update_customer']) expect(operations).not.toContain(forbidden);
  });
});
