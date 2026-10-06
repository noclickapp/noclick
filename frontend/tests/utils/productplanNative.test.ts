// Prepared native ProductPlan schema, scoped metadata and credential-selection assertions.
// Generation and a separate frontend lane are required before execution.
import { describe, expect, it } from 'vitest';
import schema from '~/schemas/nodes/productplan.json';
import { getNodeSchema, getAgentToolOperations, getNodeCredentialInfo, filterConfigForExecution } from '~/utils/nodeSchemas';
import { autoSelectCredentialFromCache, upsertCredentialsIntoCache, removeCredentialsFromCache } from '~/utils/credentialAutoSelect';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';

const operations = ['test_connection', 'list_roadmaps', 'get_roadmap', 'list_roadmap_bars', 'get_bar', 'create_bar', 'update_bar', 'delete_bar', 'list_objectives', 'get_objective', 'list_key_results', 'get_key_result', 'list_ideas', 'get_idea', 'list_launches', 'get_launch', 'list_launch_tasks', 'list_teams'];

describe('native ProductPlan preparation', () => {
  it('discovers the issued PAT and exactly 18 typed operations', () => {
    expect(getNodeSchema('automation-productplan')).toEqual(schema);
    expect(getNodeCredentialInfo('automation-productplan')?.acceptedTypes).toEqual(['productplan_pat']);
    expect(CREDENTIAL_TYPE_MAP.ProductPlanPATCredential).toBe('productplan_pat');
    expect(humanizeCredentialLabel('ProductPlanPAT')).toBe('ProductPlan PAT');
    const defs = schema.$defs as Record<string, any>;
    expect(Object.values(defs).filter(d => d.properties?.operation?.const).map(d => d.properties.operation.const).sort()).toEqual([...operations].sort());
    expect(defs.ProductPlanPATCredential.properties.personal_access_token['ui:widget']).toBe('password');
    expect(defs.ProductPlanPATCredential['x-credential-instructions']).toContain('Bearer TOKEN');
    expect(defs.ProductPlanCreateBarConfig.properties.tags['ui:widget']).toBe('list');
    expect(defs.ProductPlanCreateBarConfig.properties.tags.type).toBe('array');
    expect(defs.ProductPlanUpdateBarConfig.properties.description['ui:widget']).toBe('textarea');
    expect(defs.ProductPlanUpdateBarConfig.properties.description_mode.default).toBe('keep');
  });

  it('selects only owned current native credentials and preserves deliberate clear modes', () => {
    const owned = 'productplan-owned-fixture', foreign = 'productplan-foreign-fixture';
    try {
      upsertCredentialsIntoCache([
        { id: owned, name: 'Owned', credential_type: 'productplan_pat', owned_by_me: true },
        { id: foreign, name: 'Foreign', credential_type: 'productplan_pat', owned_by_me: false },
      ]);
      expect(autoSelectCredentialFromCache('automation-productplan')).toEqual({ productplan_pat: owned });
      const cfg = filterConfigForExecution('automation-productplan', { operation: 'update_bar', roadmap_id: 1, bar_id: 2, confirm_mutation: true, description_mode: 'clear', tags_mode: 'clear', endpoint: '/users', personal_access_token: 'omit', parked: false, share: true });
      expect(cfg.description_mode).toBe('clear');
      expect(cfg.tags_mode).toBe('clear');
      for (const key of ['endpoint', 'personal_access_token', 'parked', 'share']) expect(cfg).not.toHaveProperty(key);
    } finally {
      removeCredentialsFromCache([owned, foreign]);
    }
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
