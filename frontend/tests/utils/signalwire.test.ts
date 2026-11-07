// Checks the actual SignalWire node and shared schema/credential consumers.
// Real canvas rendering, account permissions and delivery require later gates.
import { describe, expect, it } from 'vitest';
import { SignalWireNode } from '~/components/workflow/nodes/integrations/signalwire';
import { getNodeCredentialInfo, NODE_SCHEMAS } from '~/utils/nodeSchemas';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';

describe('SignalWire native wiring', () => {
  it('uses the project Basic family with explicit Space and project fields', () => {
    expect(SignalWireNode.type).toBe('automation-signalwire');
    expect(getNodeCredentialInfo(SignalWireNode.type)?.acceptedTypes).toEqual(['signalwire_project_token']);
    expect(CREDENTIAL_TYPE_MAP.SignalWireProjectTokenCredential).toBe('signalwire_project_token');
    expect(humanizeCredentialLabel('SignalWireProjectToken')).toBe('SignalWire Project Token');
    const credential = NODE_SCHEMAS[SignalWireNode.type].$defs.SignalWireProjectTokenCredential;
    expect(credential.required).toEqual(expect.arrayContaining(['space_url', 'project_id', 'api_token']));
    expect(credential.properties.api_token['ui:widget']).toBe('password');
    expect(credential['x-oauth-provider']).toBeUndefined();
  });

  it('keeps effects and bounded selectors in the real schema', () => {
    const defs = NODE_SCHEMAS[SignalWireNode.type].$defs;
    expect(defs.SendSMS.required).toContain('confirm_send');
    expect(defs.SendSMS['x-operation-effect']).toContain('not delivered');
    expect(defs.RedactMessage.required).toContain('confirm_redact');
    expect(defs.RedactMessage['x-operation-effect']).toContain('Irreversibly');
    expect(defs.GetNumber.properties.phone_number_id['x-resource-type']).toBe('signalwire_phone_number_id');
    expect(defs.ListCalls.properties.page_size.maximum).toBe(100);
    expect(defs.SendSMS.properties).not.toHaveProperty('status_callback');
    expect(defs.RenameNumber.properties).not.toHaveProperty('call_handler');
  });
});
