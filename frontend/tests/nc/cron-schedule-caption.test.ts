// Verifies the cron node card caption derivation (fix for schedules being
// invisible on the canvas). Runs the real getScheduleCaption against the
// frequency/time mappings the AI builder and schedule widget produce.
import { nc } from '~/lib/nc';
import { getScheduleCaption } from '~/components/workflow/nodes/CronTriggerNode';

export default async function () {
    const cases: Array<[string, Record<string, unknown> | undefined, string | undefined]> = [
        ['daily 9am', { schedules: [{ frequency: 'day', hour: 9, minute: 0 }] }, '9:00 AM daily'],
        ['daily 6:30pm', { schedules: [{ frequency: 'day', hour: 18, minute: 30 }] }, '6:30 PM daily'],
        ['weekly Mon 8am', { schedules: [{ frequency: 'week', dayOfWeek: 1, hour: 8, minute: 0 }] }, 'Mon 8:00 AM'],
        ['every 2h', { schedules: [{ frequency: 'hours', interval: 2 }] }, 'every 2h'],
        ['every 15m', { schedules: [{ frequency: 'minutes', interval: 15 }] }, 'every 15m'],
        ['monthly 1st', { schedules: [{ frequency: 'month', dayOfMonth: 1, hour: 0, minute: 0 }] }, '1st 12:00 AM'],
        ['two entries -> +1', { schedules: [{ frequency: 'day', hour: 9, minute: 0 }, { frequency: 'day', hour: 17, minute: 0 }] }, '9:00 AM daily +1'],
        ['string-coerced values', { schedules: [{ frequency: 'day', hour: '7', minute: '5' }] }, '7:05 AM daily'],
        ['no schedules key -> undefined', {}, undefined],
        ['empty schedules -> undefined', { schedules: [] }, undefined],
        ['undefined config -> undefined', undefined, undefined],
        ['reference-only entry -> undefined', { schedules: ['{{n.values.s}}'] }, undefined],
    ];

    for (const [name, config, expected] of cases) {
        const got = getScheduleCaption(config);
        nc.assert.equal(got, expected, `${name}: expected "${expected}", got "${got}"`);
    }

    return { passed: cases.length };
}
