// Read-only live check with a Facebook trigger's configuration panel open.
// Run once in Manual mode and once in Managed mode; it does not register a
// Page, alter configuration, read credentials or issue a provider request.
import { nc } from '~/lib/nc';

export default async function () {
    nc.assert.truthy(document.querySelector('[data-field-key="callback_mode"]'), 'Facebook trigger callback-mode selector is visible');
    const managed = Boolean(document.querySelector('[data-field-key="page_id"]'));
    const manual = Boolean(document.querySelector('[data-field-key="verify_token"]'));
    nc.assert.equal(Number(managed) + Number(manual), 1, 'Only the selected callback mode is rendered');
    nc.assert.equal(Boolean(document.querySelector('[data-field-key="app_secret"]')), manual, 'Manual signing-secret input is absent from managed mode');
    nc.assert.equal(Boolean(document.querySelector('[data-field-key="subscription_status"]')), managed, 'Managed registration status appears only in managed mode');
    return { managed, manual };
}
