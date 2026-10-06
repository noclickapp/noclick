import { describe, expect, it } from 'vitest';
import { PrintifyNode } from '~/components/workflow/nodes/PrintifyNode';
import { getNodeCredentialInfo, NODE_SCHEMAS } from '~/utils/nodeSchemas';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';

describe('Printify native credential and node wiring', () => {
  it('registers the exact provider node and both supplied credential families', () => {
    expect(PrintifyNode.type).toBe('automation-printify');
    expect(NODE_SCHEMAS[PrintifyNode.type]).toBeDefined();
    expect(getNodeCredentialInfo(PrintifyNode.type)?.acceptedTypes).toEqual(['printify_pat', 'printify_oauth_access_token']);
    expect(CREDENTIAL_TYPE_MAP.PrintifyPATCredential).toBe('printify_pat');
    expect(CREDENTIAL_TYPE_MAP.PrintifyOAuthAccessTokenCredential).toBe('printify_oauth_access_token');
  });

  it('names the two manual token methods without inventing an OAuth popup', () => {
    expect(humanizeCredentialLabel('PrintifyPATCredential')).toBe('Printify PAT');
    expect(humanizeCredentialLabel('PrintifyOAuthAccessTokenCredential')).toBe('Printify OAuth Access Token');
    const schema = NODE_SCHEMAS[PrintifyNode.type];
    expect(schema.$defs.PrintifyOAuthAccessTokenCredential['x-oauth-provider']).toBeUndefined();
    expect(schema.$defs.PrintifyOAuthAccessTokenCredential.required).toContain('expires_at');
  });
});
