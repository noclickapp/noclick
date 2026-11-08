import { beforeAll, describe, expect, it } from 'vitest';
import schema from '~/schemas/nodes/serpstat.json';
import { loadNodeSchemas, getNodeSchema, getNodeCredentialInfo, getAgentToolOperations, filterConfigForExecution } from '~/utils/nodeSchemas';
import { upsertCredentialsIntoCache, removeCredentialsFromCache } from '~/utils/credentialAutoSelect';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
const operations = ['test_connection', 'get_credit_limits', 'list_projects', 'get_domain_overview', 'get_domain_history', 'list_domain_keywords', 'list_domain_competitors', 'get_keyword_metrics', 'list_related_keywords', 'get_keyword_trends', 'get_keyword_top', 'get_backlink_summary', 'list_referring_domains', 'list_rank_projects', 'list_rank_regions', 'get_rank_status', 'list_rank_keywords', 'list_audit_reports', 'get_audit_status', 'get_audit_categories'];

describe('self-registering Serpstat', () => {
  beforeAll(async () => { await loadNodeSchemas(['automation-serpstat']); });
  it('discovers the actual token family and exactly 20 closed read operations', () => {
    expect(getNodeSchema('automation-serpstat')).toEqual(schema);
    expect(getNodeCredentialInfo('automation-serpstat')?.acceptedTypes).toEqual(['serpstat_api_token']);
    expect(CREDENTIAL_TYPE_MAP.SerpstatApiTokenCredential).toBe('serpstat_api_token');
    expect(credentialRequirements('automation-serpstat').map(methodFromRequirement).map(m => m.method_kind)).toEqual(['api_key']);
    const defs = schema.$defs as Record<string, any>;
    expect(Object.values(defs).filter(d => d.properties?.operation?.const).map(d => d.properties.operation.const).sort()).toEqual([...operations].sort());
    expect(defs.SerpstatApiTokenCredential.properties.api_token['ui:widget']).toBe('password');
    expect(defs.SerpstatApiTokenCredential['x-credential-instructions']).toContain('sandbox');
    expect(defs.SerpstatApiTokenCredential).not.toHaveProperty('x-oauth-provider');
    expect(defs.SerpstatKeywordMetricsConfig.properties.keywords['ui:widget']).toBe('list');
    expect(defs.SerpstatDomainOverviewConfig.properties.search_engine.enum).toContain('g_us');
    expect(defs.SerpstatAuditReportsConfig.properties.offset.description).toContain('batch number');
  });

  it('selects current owned tokens and preserves configured rank scope', () => {
    const own = 'serpstat-owned', foreign = 'serpstat-foreign';
    try {
      upsertCredentialsIntoCache([
        { id: own, name: 'Owned', credential_type: 'serpstat_api_token', owned_by_me: true },
        { id: foreign, name: 'Foreign', credential_type: 'serpstat_api_token', owned_by_me: false },
      ]);
      expect(autoSelectCredentialFromCache('automation-serpstat')).toEqual({ serpstat_api_token: own });
      const cfg = filterConfigForExecution('automation-serpstat', { operation: 'get_rank_status', rank_project_id: '81', rank_region_id: '82' });
      expect(cfg.rank_project_id).toBe('81'); expect(cfg.rank_region_id).toBe('82');
      expect(cfg).toEqual({ operation: 'get_rank_status', rank_project_id: '81', rank_region_id: '82' });
      expect(schema.$defs.SerpstatRankStatusConfig.additionalProperties).toBe(false);
    } finally { removeCredentialsFromCache([own, foreign]); }
  });

  it('preserves distinct rank and audit parent scope in actual Agent metadata', () => {
    const defs = schema.$defs as Record<string, any>;
    expect(defs.SerpstatRankStatusConfig.properties.rank_region_id['x-dynamic-options'].depends_on).toBe('rank_project_id');
    expect(defs.SerpstatAuditStatusConfig.properties.audit_report_id['x-dynamic-options'].depends_on).toBe('project_id');
    const tools = getAgentToolOperations('automation-serpstat');
    expect(tools.map(t => t.operation).sort()).toEqual([...operations].sort());
    expect(tools.find(t => t.operation === 'get_rank_status')!.scopableFields).toEqual(expect.arrayContaining([
      expect.objectContaining({ field: 'rank_project_id', resourceType: 'serpstat_rank_project' }),
      expect.objectContaining({ field: 'rank_region_id', resourceType: 'serpstat_rank_region', dependsOn: 'rank_project_id' }),
    ]));
    expect(tools.find(t => t.operation === 'get_audit_status')!.scopableFields).toEqual(expect.arrayContaining([
      expect.objectContaining({ field: 'project_id', resourceType: 'serpstat_project' }),
      expect.objectContaining({ field: 'audit_report_id', resourceType: 'serpstat_audit_report', dependsOn: 'project_id' }),
    ]));
    for (const op of ['arbitrary_request', 'start_audit', 'run_project_tracking', 'invite_team_member', 'create_token']) expect(operations).not.toContain(op);
  });
});
