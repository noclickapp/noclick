// Checks native Cliniko registration and actual credential-schema consumers.
// Its source stays separate from later UI, account and runtime verification.
import { beforeAll, describe, expect, it } from 'vitest';
import { ClinikoNode } from '~/components/workflow/nodes/integrations/cliniko';
import { getNodeCredentialInfo, loadNodeSchemas, NODE_SCHEMAS } from '~/utils/nodeSchemas';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';

describe('Cliniko native wiring', () => {
  beforeAll(() => loadNodeSchemas(['automation-cliniko']));
  it('selects the issued user API-key family without an OAuth flow', () => {
    expect(ClinikoNode.type).toBe('automation-cliniko');
    expect(getNodeCredentialInfo(ClinikoNode.type)?.acceptedTypes).toEqual(['cliniko_api_key']);
    expect(CREDENTIAL_TYPE_MAP.ClinikoApiKeyCredential).toBe('cliniko_api_key');
    expect(humanizeCredentialLabel('ClinikoApiKey')).toBe('Cliniko API Key');
    const credential = NODE_SCHEMAS[ClinikoNode.type].$defs.ClinikoApiKeyCredential;
    expect(credential.properties.api_key['ui:widget']).toBe('password');
    expect(credential.required).toContain('admin_contact_email');
    expect(credential['x-oauth-provider']).toBeUndefined();
  });

  it('keeps availability parent dependencies and explicit contact archive effects', () => {
    const defs = NODE_SCHEMAS[ClinikoNode.type].$defs;
    expect(defs.ListAvailableTimes.properties.practitioner_id['x-dynamic-options'].depends_on).toBe('business_id');
    expect(defs.ListAvailableTimes.properties.appointment_type_id['x-dynamic-options'].depends_on).toBe('practitioner_id');
    expect(defs.ArchiveContact.required).toContain('confirm_archive');
    expect(defs.UpdateContact['x-operation-effect']).toContain('Omitted fields are preserved');
    expect(defs.CreateContact.properties).not.toHaveProperty('notes');
    expect(defs).not.toHaveProperty('CreatePatient');
  });
});
