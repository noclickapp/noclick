// Checks Oracle HCM native registration and real credential/schema consumers.
// Runtime, UI rendering and provider verification require separate execution.
import { beforeAll, describe, expect, it } from 'vitest';
import { OracleHCMNode } from '~/components/workflow/nodes/integrations/oracle-hcm';
import { getNodeCredentialInfo, loadNodeSchemas, NODE_SCHEMAS } from '~/utils/nodeSchemas';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';

describe('Oracle HCM native wiring', () => {
  beforeAll(async () => { await loadNodeSchemas(['automation-oracle-hcm']); });
  it('accepts both tenant-bound supplied families without inventing an OAuth flow', () => {
    expect(OracleHCMNode.type).toBe('automation-oracle-hcm');
    expect(getNodeCredentialInfo(OracleHCMNode.type)?.acceptedTypes.sort()).toEqual(['oracle_hcm_basic', 'oracle_hcm_oauth_token']);
    expect(CREDENTIAL_TYPE_MAP.OracleHCMBasicCredential).toBe('oracle_hcm_basic');
    expect(CREDENTIAL_TYPE_MAP.OracleHCMSuppliedOAuthCredential).toBe('oracle_hcm_oauth_token');
    expect(humanizeCredentialLabel('Oracle HCM Basic Account')).toBe('Oracle HCM Basic Account');
    const defs = NODE_SCHEMAS[OracleHCMNode.type].$defs;
    for (const key of ['OracleHCMBasicCredential', 'OracleHCMSuppliedOAuthCredential']) {
      expect(defs[key].required).toEqual(expect.arrayContaining(['tenant_url', 'api_version']));
      expect(defs[key]['x-oauth-provider']).toBeUndefined();
    }
    expect(defs.OracleHCMBasicCredential.properties.password['ui:widget']).toBe('password');
    expect(defs.OracleHCMSuppliedOAuthCredential.properties.access_token['ui:widget']).toBe('password');
  });

  it('keeps opaque location scope and explicit date-effective delete semantics', () => {
    const defs = NODE_SCHEMAS[OracleHCMNode.type].$defs;
    expect(defs.GetLocation.properties.location_key['x-resource-type']).toBe('oracle_hcm_location_key');
    expect(defs.UpdateLocation.required).toContain('range_mode');
    expect(defs.DeleteLocation.required).toContain('confirm_delete_changes');
    expect(defs.DeleteLocation['x-operation-effect']).toContain('DELETE_CHANGES');
    expect(defs.CreateLocation.required).toEqual(expect.arrayContaining(['set_id', 'set_code', 'effective_start_date', 'effective_end_date']));
    expect(defs.CreateLocation.properties).not.toHaveProperty('addresses');
    expect(defs).not.toHaveProperty('UpdateWorker');
  });
});
