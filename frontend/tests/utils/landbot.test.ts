// Checks native Landbot registration and the actual credential-schema consumers.
// Provider behavior is verified separately by the backend tests.
import { beforeAll, describe, expect, it } from 'vitest';
import { LandbotNode } from '~/components/workflow/nodes/integrations/landbot';
import { getNodeCredentialInfo, loadNodeSchemas, NODE_SCHEMAS } from '~/utils/nodeSchemas';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';

beforeAll(() => loadNodeSchemas(['automation-landbot']));

describe('Landbot Platform native wiring', () => {
  it('exposes only the workspace agent-token credential', () => {
    expect(LandbotNode.type).toBe('automation-landbot');
    expect(getNodeCredentialInfo(LandbotNode.type)?.acceptedTypes).toEqual(['landbot_agent_token']);
    expect(CREDENTIAL_TYPE_MAP.LandbotAgentTokenCredential).toBe('landbot_agent_token');
    expect(humanizeCredentialLabel('LandbotAgentToken')).toBe('Landbot Agent Token');
    const credential = NODE_SCHEMAS[LandbotNode.type].$defs.LandbotAgentTokenCredential;
    expect(credential.properties.agent_token['ui:widget']).toBe('password');
    expect(credential['x-oauth-provider']).toBeUndefined();
  });

  it('preserves channel and customer picker dependencies and explicit field deletion', () => {
    const defs = NODE_SCHEMAS[LandbotNode.type].$defs;
    expect(defs.GetCustomer.properties.customer_id['x-dynamic-options'].depends_on).toBe('channel_id');
    expect(defs.GetCustomerField.properties.field_name['x-dynamic-options'].depends_on).toBe('customer_id');
    expect(defs.DeleteCustomerField.required).toContain('confirm_delete');
    expect(defs.CreateCustomerField['x-operation-effect']).toContain('never silently overwrites');
  });
});
