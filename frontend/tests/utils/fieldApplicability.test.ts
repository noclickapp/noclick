// Credential applicability is shared by configuration surfaces.
// Unknown credentials preserve the question; QR hides only Cloud-specific fields.
import { expect, it } from 'vitest';
import { isFieldApplicable } from '~/utils/schemaFieldExtractor';
import whatsapp from '~/schemas/nodes/whatsapp.json';

it('uses the generated WhatsApp schema to distinguish Cloud API from QR', () => {
    const field =
        whatsapp.$defs.WhatsAppReceiveMessageConfig.properties.verify_token;
    expect(isFieldApplicable(field, { whatsapp_qr: 'qr' })).toBe(false);
    expect(isFieldApplicable(field, { whatsapp_access_token: 'cloud' })).toBe(
        true
    );
    expect(isFieldApplicable(field, {})).toBe(true);
    expect(isFieldApplicable({ type: 'boolean' }, { whatsapp_qr: 'qr' })).toBe(
        true
    );
});
