import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { LeadfeederNode } from '../../app/components/workflow/nodes/integrations/leadfeeder';
import { getAgentToolOperations, getNodeCredentialInfo, loadNodeSchemas, NODE_SCHEMAS } from '../../app/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '../../app/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '../../app/utils/credentialLabels';
import metadata from '../../app/schemas/nodeMeta/leadfeeder.json';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';

await loadNodeSchemas(['automation-leadfeeder']);

describe('Leadfeeder native company reads', () => {
  it('exposes seventeen real native operations and account-scoped pickers', () => {
    const operations = getAgentToolOperations('automation-leadfeeder');
    expect(operations.map(op => op.operation).sort()).toEqual([
      'get_account', 'get_campaign', 'get_company', 'get_company_list', 'get_custom_feed',
      'list_accounts', 'list_campaigns', 'list_company_fields', 'list_company_list_members', 'list_company_lists',
      'list_countries', 'list_custom_feeds', 'list_feed_folders', 'list_industries', 'list_tags', 'list_visitor_companies',
      'search_companies',
    ]);
    expect(LeadfeederNode.type).toBe('automation-leadfeeder');
    expect(LeadfeederNode.label).toBe('Leadfeeder (Dealfront)');
    expect(metadata.nodeMeta).toMatchObject({ agentToolProvider: true });
    const schema = NODE_SCHEMAS['automation-leadfeeder'];
    expect(schema.$defs.GetCompany.properties.company_id['x-dynamic-options'].depends_on).toBe('account_id');
    expect(schema.$defs.ListCompanyListMembers.properties.list_id['x-dynamic-options'].depends_on).toBe('account_id');
    expect(schema.$defs.GetCompany.properties.acknowledge_credit_use.default).toBe(false);
    expect(schema.$defs.SearchCompanies.properties.page_size.maximum).toBe(100);
    expect(operations.find(op => op.operation === 'get_company')?.scopableFields)
      .toEqual(expect.arrayContaining([expect.objectContaining({ field: 'company_id', dependsOn: 'account_id', resourceType: 'leadfeeder_company' })]));
    expect(JSON.stringify(schema)).not.toContain('x-creator');
    expect(JSON.stringify(schema)).not.toContain('x-oauth-provider');
  });

  it('uses the current issued-key family and readable labels', () => {
    expect(credentialRequirements('automation-leadfeeder').map(requirement => methodFromRequirement(requirement).method_kind)).toEqual(['api_key']);
    expect(getCredentialTypeFromSchemaTitle('LeadfeederApiCredential')).toBe('leadfeeder_api_key');
    expect(getCredentialTypeFromSchemaTitle('Leadfeeder API Access')).toBe('leadfeeder_api_key');
    expect(getNodeCredentialInfo('automation-leadfeeder')?.acceptedTypes).toContain('leadfeeder_api_key');
    expect(humanizeCredentialLabel('Leadfeeder API Access')).toBe('Leadfeeder API Access');
    expect(metadata.providerLabels.leadfeeder).toBe('Leadfeeder API Access');
  });

  it('retains the unchanged official site favicon', () => {
    const bytes = readFileSync(new URL('../../public/icons/leadfeeder.svg', import.meta.url));
    expect(bytes.length).toBe(1234);
    expect(createHash('sha256').update(bytes).digest('hex')).toBe('644d96a89c7eea8ad87cb6e64e2c09c3f484a6b5a847c2376fd7988b834096ec');
  });
});
