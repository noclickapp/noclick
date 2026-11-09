import { beforeAll, describe, expect, it } from 'vitest';
import { validateConfigForm } from '~/utils/nodeConfigFormValidation';
import { loadNodeSchemas } from '~/utils/nodeSchemas';

beforeAll(async () => {
    await loadNodeSchemas(['automation-unione']);
}, 30000);

describe('UniOne structured inputs', () => {
    it('accepts JSON editor text and tool arrays without limiting JSON text to ten characters', () => {
        for (const tags of ['["receipt", "order-confirmation"]', ['receipt', 'order-confirmation']]) {
            const result = validateConfigForm('automation-unione', {
                email: 'email@example.com', from_email: 'sender@example.com',
                subject: 'Order confirmation', plaintext: 'Thanks for your order', tags,
                global_substitutions: '{"CustomerId":"12452"}',
            }, 'send_email');
            expect(result).toEqual({ valid: true, errors: [] });
        }
    });

    it('accepts webhook events from the JSON editor', () => {
        expect(validateConfigForm('automation-unione', {
            url: 'https://example.com/webhook', events: '{"email_status":["delivered"]}',
        }, 'set_webhook')).toEqual({ valid: true, errors: [] });
    });
});
