// Verifies getTriggerRunPrompt / getAutomaticTriggers: a workflow that starts
// only on automatic triggers (with no manual Run trigger) should prompt the
// trigger-info popup, while a manual entry point or a plain chain should not.
import { nc } from '~/lib/nc';
import {
    getTriggerRunPrompt,
    getAutomaticTriggers,
    hasManualEntry,
} from '~/utils/workflowTriggers';

export default async function () {
    const node = (id: string, type: string, data: Record<string, unknown> = {}) => ({ id, type, data });
    const nodeWithConfig = (id: string, type: string, config: Record<string, unknown>) => ({
        id,
        type,
        data: { config },
    });

    // 1. Dedicated webhook trigger, no manual entry → prompt with 1 trigger.
    const webhookOnly = [node('w', 'trigger-webhook'), node('a', 'automation-ai-agent')];
    const p1 = getTriggerRunPrompt(webhookOnly);
    nc.assert.equal(p1?.length, 1, 'webhook-only workflow should prompt one trigger');
    nc.assert.truthy(
        (p1?.[0].description ?? '').toLowerCase().includes('http'),
        'webhook trigger description should mention HTTP',
    );

    // 2. Same workflow + a manual Run trigger → no prompt.
    const withManual = [...webhookOnly, node('r', 'trigger-run')];
    nc.assert.equal(getTriggerRunPrompt(withManual), null, 'manual Run trigger should suppress the prompt');
    nc.assert.truthy(hasManualEntry(withManual), 'hasManualEntry should be true with trigger-run');

    // 3. A form node surfaces the prompt (pressing Run can't submit the form) with
    //    its hosted form page as an openable link.
    const formTrigger = getAutomaticTriggers([
        nodeWithConfig('f', 'interface-form', { webhook_url: 'https://forms.example.com/abc' }),
    ]);
    nc.assert.equal(formTrigger.length, 1, 'form trigger should surface as an automatic trigger');
    nc.assert.truthy(
        (formTrigger[0].description ?? '').toLowerCase().includes('form'),
        'form trigger description should mention the form',
    );
    const formParam = formTrigger[0].params?.[0];
    nc.assert.equal(formParam?.href, 'https://forms.example.com/abc', 'form trigger exposes the hosted form URL as an openable link');
    nc.assert.truthy(formParam?.mono, 'form URL is copyable (mono)');
    nc.assert.equal(
        getTriggerRunPrompt([node('f', 'interface-form', { config: { webhook_url: 'https://forms.example.com/abc' } })])?.length,
        1,
        'a form-only workflow should prompt',
    );

    // 3b. A manual Run trigger still suppresses the prompt even alongside a form.
    //     Uses the legacy pre-merge type to pin alias resolution in getAutomaticTriggers.
    const formPlusManual = [node('f', 'trigger-form-input'), node('r', 'trigger-run')];
    nc.assert.equal(getTriggerRunPrompt(formPlusManual), null, 'a manual Run trigger suppresses the prompt');

    // 4. Integration trigger op (Gmail "new email") → prompt with a real description.
    const gmailTrigger = [node('g', 'automation-gmail', { operation: 'poll_for_new_emails' })];
    const p4 = getTriggerRunPrompt(gmailTrigger);
    nc.assert.equal(p4?.length, 1, 'gmail trigger op should prompt');
    nc.assert.truthy((p4?.[0].title ?? '').length > 0, 'gmail trigger should resolve a title');

    // 5. Integration node with a NON-trigger op → no prompt.
    const gmailSend = [node('g', 'automation-gmail', { operation: 'create_email_draft' })];
    nc.assert.equal(getTriggerRunPrompt(gmailSend), null, 'non-trigger gmail op should not prompt');

    // 6. Disabled trigger is ignored.
    const disabled = [node('w', 'trigger-webhook', { disabled: true })];
    nc.assert.equal(getAutomaticTriggers(disabled).length, 0, 'disabled trigger should be skipped');

    // 7. Plain chain (no triggers) → no prompt.
    const plain = [node('h', 'automation-http-request'), node('a', 'automation-ai-agent')];
    nc.assert.equal(getTriggerRunPrompt(plain), null, 'plain chain should run without a prompt');

    // 8. Sheets "new row" surfaces the human-readable spreadsheet + sheet it watches.
    const sheets = getAutomaticTriggers([
        nodeWithConfig('s', 'automation-google-sheets', {
            operation: 'on_new_row',
            spreadsheet_id: '1AbC',
            spreadsheet_id__label: 'Q3 Budget',
            sheet_name: 'Expenses',
        }),
    ]);
    const sheetParams = sheets[0]?.params ?? [];
    nc.assert.equal(sheetParams.length, 2, 'sheets trigger should surface spreadsheet + sheet');
    nc.assert.equal(sheetParams[0].value, 'Q3 Budget', 'spreadsheet_id resolves to its __label');
    nc.assert.equal(sheetParams[1].value, 'Expenses', 'sheet name is surfaced');

    // 9. Email trigger surfaces the address to send to, marked copyable (mono).
    const email = getAutomaticTriggers([nodeWithConfig('e', 'trigger-email', { local_part: 'orders' })]);
    const emailParam = email[0]?.params?.[0];
    nc.assert.equal(emailParam?.value, 'orders@example.com', 'email trigger surfaces the full address');
    nc.assert.truthy(emailParam?.mono, 'address is marked monospace/copyable');

    // 10. Plain filter fields surface (Gmail query) while plumbing (max_results,
    //     mark_as_read) is excluded.
    const gmailPoll = getAutomaticTriggers([
        nodeWithConfig('g2', 'automation-gmail', {
            operation: 'poll_for_new_emails',
            query: 'from:boss@acme.com is:unread',
            max_results: 50,
            mark_as_read: 'true',
        }),
    ]);
    const gmailParams = gmailPoll[0]?.params ?? [];
    nc.assert.equal(gmailParams.length, 1, 'gmail poll shows only the search query (no max_results/mark_as_read)');
    nc.assert.equal(gmailParams[0]?.value, 'from:boss@acme.com is:unread', 'gmail query is surfaced');

    // 11. Plumbing-only triggers (webhook_url, subscription_status) surface nothing.
    const hubspot = getAutomaticTriggers([
        nodeWithConfig('h2', 'automation-hubspot', { operation: 'on_contact_created', subscription_status: 'active' }),
    ]);
    nc.assert.equal(hubspot[0]?.params.length, 0, 'plumbing-only trigger shows no params');

    // 12. Cron trigger surfaces each schedule in plain language + the timezone for
    //     time-of-day schedules.
    const cron = getAutomaticTriggers([
        nodeWithConfig('cr', 'trigger-cron', {
            timezone: 'America/New_York',
            schedules: [
                { frequency: 'day', hour: 9, minute: 0 },
                { frequency: 'week', dayOfWeek: 1, hour: 8, minute: 30 },
            ],
        }),
    ]);
    const cronParams = cron[0]?.params ?? [];
    nc.assert.equal(cronParams.length, 3, 'two schedules + timezone');
    nc.assert.equal(cronParams[0].value, 'Daily at 9:00 AM', 'daily schedule reads in plain language');
    nc.assert.equal(cronParams[1].value, 'Every Monday at 8:30 AM', 'weekly schedule reads in plain language');
    nc.assert.equal(cronParams[2].label, 'Timezone', 'timezone is surfaced for time-of-day schedules');
    nc.assert.equal(cronParams[2].value, 'America/New_York', 'timezone value is shown');

    // 12b. An interval cron (every 5 minutes) needs no timezone.
    const cronInterval = getAutomaticTriggers([
        nodeWithConfig('cr2', 'trigger-cron', {
            timezone: 'UTC',
            schedules: [{ frequency: 'minutes', interval: 5 }],
        }),
    ]);
    const intervalParams = cronInterval[0]?.params ?? [];
    nc.assert.equal(intervalParams.length, 1, 'interval schedule shows no timezone');
    nc.assert.equal(intervalParams[0].value, 'Every 5 minutes', 'interval schedule reads in plain language');

    return {
        p1Count: p1?.length,
        gmailTitle: p4?.[0].title,
        sheetParams,
        emailAddress: emailParam?.value,
        gmailQuery: gmailParams[0]?.value,
    };
}
