// Checks Veryfi's actual node, generated fields and credential consumers.
// Canvas rendering, real permissions and processing require later execution gates.
import { describe, expect, it } from 'vitest';
import { VeryfiNode } from '~/components/workflow/nodes/integrations/veryfi';
import { getNodeCredentialInfo, NODE_SCHEMAS, loadAllNodeSchemas } from '~/utils/nodeSchemas';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';

await loadAllNodeSchemas();

describe('Veryfi native wiring', () => {
  it('discovers both actual key families and protected signing fields', () => {
    expect(VeryfiNode.type).toBe('automation-veryfi');
    expect(getNodeCredentialInfo(VeryfiNode.type)?.acceptedTypes).toEqual(['veryfi_bearer_api_key', 'veryfi_standard_api_key']);
    const defs = NODE_SCHEMAS[VeryfiNode.type].$defs;
    for (const [title, type] of [['VeryfiBearerAPIKeyCredential', 'veryfi_bearer_api_key'], ['VeryfiStandardAPIKeyCredential', 'veryfi_standard_api_key']]) {
      expect(CREDENTIAL_TYPE_MAP[title]).toBe(type);
      expect(defs[title].required).toEqual(expect.arrayContaining(['client_id', 'api_key']));
      expect(defs[title].properties.api_key['ui:widget']).toBe('password');
      expect(defs[title].properties.client_secret['ui:widget']).toBe('password');
      expect(defs[title]['x-oauth-provider']).toBeUndefined();
    }
    expect(defs.VeryfiStandardAPIKeyCredential.required).toContain('username');
    expect(humanizeCredentialLabel('VeryfiBearerAPIKey')).toBe('Veryfi Bearer API Key');
  });

  it('keeps upload effects, private bounds and dependent tag selectors', () => {
    const defs = NODE_SCHEMAS[VeryfiNode.type].$defs;
    expect(defs.ProcessDocument.required).toEqual(expect.arrayContaining(['confirm_processing', 'file_data', 'idempotency_key']));
    expect(defs.ProcessDocument['x-operation-effect']).toContain('billed');
    expect(defs.ProcessDocumentAsync['x-operation-effect']).toContain('before extraction finishes');
    expect(defs.ProcessDocument.properties.file_data.maxLength).toBe(2796204);
    expect(defs.ProcessDocument.properties).not.toHaveProperty('file_url');
    expect(defs.UpdateMetadata.properties).not.toHaveProperty('total');
    expect(defs.DeleteDocument.required).toContain('confirm_delete');
    expect(defs.UnlinkTag.properties.tag_id['x-dynamic-options'].depends_on).toBe('document_id');
    expect(defs.ListDocuments.properties.page_size.maximum).toBe(50);
  });
});
