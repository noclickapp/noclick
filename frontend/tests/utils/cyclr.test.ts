// Covers the actual native Cyclr schema and credential consumers after generation.
// These unrun fixtures do not establish real console or canvas access.
import { beforeAll, describe, expect, it } from 'vitest';
import { CyclrNode } from '~/components/workflow/nodes/integrations/cyclr';
import { getNodeCredentialInfo, loadNodeSchemas, NODE_SCHEMAS } from '~/utils/nodeSchemas';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';

describe('Cyclr native wiring', () => {
  beforeAll(() => loadNodeSchemas([CyclrNode.type]));
  it('discovers supplied console OAuth and its required account binding', () => {
    expect(CyclrNode.type).toBe('automation-cyclr');
    expect(getNodeCredentialInfo(CyclrNode.type)?.acceptedTypes).toEqual(['cyclr_oauth_token']);
    expect(CREDENTIAL_TYPE_MAP.CyclrOAuthTokenCredential).toBe('cyclr_oauth_token');
    const credential = NODE_SCHEMAS[CyclrNode.type].$defs.CyclrOAuthTokenCredential;
    expect(credential.required).toEqual(expect.arrayContaining(['access_token', 'account_id']));
    expect(credential.properties.access_token['ui:widget']).toBe('password');
    expect(credential.properties.region.enum).toEqual(['us', 'us2', 'uk', 'eu']);
    expect(credential['x-oauth-provider']).toBeUndefined();
    expect(humanizeCredentialLabel('CyclrOAuthToken')).toBe('Cyclr OAuth Token');
  });

  it('keeps nine metadata reads, names opt-in and the step parent', () => {
    const defs = NODE_SCHEMAS[CyclrNode.type].$defs;
    const operations = Object.values(defs).flatMap((definition: any) => definition.properties?.operation?.const ? [definition.properties.operation.const] : []);
    expect(operations.sort()).toEqual(['get_account', 'get_cycle', 'get_cycle_step', 'get_template', 'list_accounts', 'list_connector_catalog', 'list_cycle_steps', 'list_cycles', 'list_templates']);
    expect(defs.GetCycleStep.required).toEqual(expect.arrayContaining(['cycle_id', 'step_id']));
    expect(defs.GetCycleStep.properties.step_id['x-dynamic-options'].depends_on).toBe('cycle_id');
    expect(defs.GetAccount.properties.include_names.default).toBe(false);
    expect(defs.ListCycles.properties.page_size.maximum).toBe(100);
    expect(defs.ListCycles.properties).not.toHaveProperty('account_id');
    expect(defs.ListCycles.additionalProperties).toBe(false);
  });
});
