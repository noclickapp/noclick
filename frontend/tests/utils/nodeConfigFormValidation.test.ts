// The config panel's field validation judges a node the way the runtime will:
// the committed operation's fields only, any IANA zone a schedule can run in,
// and null/"" on a defaulted field as unset. Working triggers read as valid,
// genuinely incomplete or unrunnable configs still name the field at fault.
import { beforeAll, describe, expect, test } from 'vitest';
import type { Node } from '@xyflow/react';

let validateConfigForm: typeof import('~/utils/nodeConfigFormValidation').validateConfigForm;
let validateNode: typeof import('~/utils/workflowNodeValidation').validateNode;

beforeAll(async () => {
    ({ validateConfigForm } = await import('~/utils/nodeConfigFormValidation'));
    ({ validateNode } = await import('~/utils/workflowNodeValidation'));
    await (await import('~/utils/nodeSchemas')).loadNodeSchemas(['automation-whatsapp', 'trigger-cron']);
}, 30000);

// A connected WhatsApp message trigger as the canvas holds it (mirrors included).
const WHATSAPP_TRIGGER = {
    webhook_id: 'wh-1',
    webhook_url: 'https://wh-1.example.run',
    wahooks_registered: true,
    trigger_registered: true,
    registered_operation: 'receive_message',
    is_active: true,
    include_group_messages: 'false',
};

// A registered daily schedule in a zone outside the picker's shortlist.
const DAILY_SCHEDULE = {
    timezone: 'Asia/Jerusalem',
    schedules: [{ hour: 9, minute: 0, frequency: 'day' }],
    schedule_id: 'sched-1',
    webhook_url: 'https://wh-2.example.run',
    trigger_registered: true,
    next_run: '2026-11-01T07:00:00Z',
};

const fieldKeys = (result: { errors: { fieldKey?: string }[] }) => result.errors.map(e => e.fieldKey);

describe('a WhatsApp message trigger', () => {
    test('has no field errors when it is set up', () => {
        expect(validateConfigForm('automation-whatsapp', WHATSAPP_TRIGGER, 'receive_message')).toEqual({ valid: true, errors: [] });
    });

    test('is judged on its own action, not the first one the node offers', () => {
        // The node's first action is send_text_message, which needs a recipient and a body.
        expect(fieldKeys(validateConfigForm('automation-whatsapp', WHATSAPP_TRIGGER, 'send_text_message')).sort()).toEqual(['body', 'to']);
        expect(validateConfigForm('automation-whatsapp', WHATSAPP_TRIGGER, 'receive_message').errors).toEqual([]);
    });

    test('with no action picked asks for one instead of the first action\'s fields', () => {
        expect(validateConfigForm('automation-whatsapp', {}, undefined)).toEqual({
            valid: false,
            errors: [{ message: 'Choose an action', type: 'general' }],
        });
    });

    test('still needs its connection', () => {
        const node = (credentialIds: Record<string, string>) =>
            ({ id: 'wa', type: 'automation-whatsapp', position: { x: 0, y: 0 }, data: { operation: 'receive_message', credentialIds, config: WHATSAPP_TRIGGER } }) as Node;
        expect(validateNode(node({ whatsapp_qr: 'cred-1' }))).toEqual({ isComplete: true, issues: [] });
        expect(validateNode(node({})).issues.map(i => i.type)).toEqual(['missing_credentials']);
    });
});

describe('a send step', () => {
    test('still reports the fields it is missing', () => {
        const result = validateConfigForm('automation-whatsapp', { to: '15550001111' }, 'send_text_message');
        expect(result.valid).toBe(false);
        expect(result.errors).toEqual([{ message: 'is required', fieldKey: 'body', fieldLabel: 'Message Text', type: 'field' }]);
    });
});

describe('a schedule', () => {
    test('has no field errors when it is set up, in any zone the scheduler can run', () => {
        expect(validateConfigForm('trigger-cron', DAILY_SCHEDULE, undefined)).toEqual({ valid: true, errors: [] });
        for (const timezone of ['Europe/Helsinki', 'Africa/Casablanca', 'Asia/Calcutta', 'US/Eastern', 'UTC']) {
            expect(validateConfigForm('trigger-cron', { ...DAILY_SCHEDULE, timezone }, undefined).errors).toEqual([]);
        }
    });

    test('with no timezone saved runs in the default, so it is not an error', () => {
        for (const timezone of [null, '']) {
            expect(validateConfigForm('trigger-cron', { ...DAILY_SCHEDULE, timezone }, undefined).errors).toEqual([]);
        }
    });

    test('flags a zone that does not exist', () => {
        expect(validateConfigForm('trigger-cron', { ...DAILY_SCHEDULE, timezone: 'Mars/Olympus_Mons' }, undefined).errors).toEqual([
            { message: 'must be a valid timezone', fieldKey: 'timezone', fieldLabel: 'Timezone', type: 'field' },
        ]);
    });

    test('flags a schedule entry the runtime cannot parse', () => {
        const result = validateConfigForm('trigger-cron', { ...DAILY_SCHEDULE, schedules: [{ hour: 9, minute: 0, frequency: 'daily' }] }, undefined);
        expect(result.valid).toBe(false);
        expect(fieldKeys(result)).toEqual(['schedules']);
    });
});
