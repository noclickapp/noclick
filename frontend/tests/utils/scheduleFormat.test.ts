// Human-readable phrases for narrowed schedules — the summary line under the
// schedule widget and the Run trigger-info popup both read describeSchedule,
// so the stacked from→to constraints must phrase correctly.
import { describe, expect, it } from 'vitest';
import {
    describeSchedule,
    describeDays,
    daysLabel,
    windowLabel,
    calendarLabel,
    isTimeOfDaySchedule,
} from '~/utils/scheduleFormat';

describe('describeSchedule with narrowing constraints', () => {
    it('phrases the weekday business-hours window', () => {
        expect(
            describeSchedule({
                frequency: 'minutes',
                interval: 30,
                windowStart: '09:00',
                windowEnd: '18:00',
                daysOfWeek: [1, 2, 3, 4, 5],
            })
        ).toBe('every 30 minutes from 9:00 AM to 6:00 PM on weekdays');
    });

    it('phrases all four constraints stacked', () => {
        expect(
            describeSchedule({
                frequency: 'seconds',
                interval: 10,
                windowStart: '09:00',
                windowEnd: '18:00',
                daysOfWeek: [1, 2, 3, 4, 5],
                monthDayStart: 1,
                monthDayEnd: 15,
                monthStart: 3,
                monthEnd: 10,
            })
        ).toBe(
            'every 10 seconds from 9:00 AM to 6:00 PM on weekdays, the 1st–15th of each month, March to October'
        );
    });

    it('phrases a window without a day filter', () => {
        expect(
            describeSchedule({
                frequency: 'hours',
                interval: 2,
                windowStart: '09:15',
                windowEnd: '17:45',
            })
        ).toBe('every 2 hours from 9:15 AM to 5:45 PM');
    });

    it('phrases a day filter without a window', () => {
        expect(
            describeSchedule({
                frequency: 'minutes',
                interval: 15,
                daysOfWeek: [0, 6],
            })
        ).toBe('every 15 minutes on weekends');
    });

    it('phrases wrapping month-day and month ranges', () => {
        expect(
            describeSchedule({
                frequency: 'minutes',
                interval: 30,
                monthDayStart: 25,
                monthDayEnd: 5,
            })
        ).toBe('every 30 minutes, the 25th–5th of each month');
        expect(
            describeSchedule({
                frequency: 'day',
                hour: 9,
                minute: 0,
                monthStart: 11,
                monthEnd: 2,
            })
        ).toBe('daily at 9:00 AM, November to February');
    });

    it('collapses equal bounds to the natural point form', () => {
        expect(
            describeSchedule({
                frequency: 'day',
                hour: 9,
                minute: 0,
                monthStart: 8,
                monthEnd: 8,
            })
        ).toBe('daily at 9:00 AM, in August');
        expect(
            describeSchedule({
                frequency: 'day',
                hour: 9,
                minute: 0,
                monthDayStart: 10,
                monthDayEnd: 10,
            })
        ).toBe('daily at 9:00 AM, on the 10th of each month');
        expect(
            describeSchedule({
                frequency: 'day',
                hour: 9,
                minute: 0,
                monthDayStart: 10,
                monthDayEnd: 15,
                monthStart: 8,
                monthEnd: 8,
            })
        ).toBe('daily at 9:00 AM, the 10th–15th of August');
    });

    it('phrases custom day sets on a daily schedule', () => {
        expect(
            describeSchedule({
                frequency: 'day',
                hour: 9,
                minute: 30,
                daysOfWeek: [1, 3, 5],
            })
        ).toBe('daily at 9:30 AM on Mon, Wed, Fri');
    });

    it('phrases a year range on weekly and monthly schedules', () => {
        expect(
            describeSchedule({
                frequency: 'week',
                hour: 17,
                minute: 0,
                dayOfWeek: 5,
                monthStart: 3,
                monthEnd: 10,
            })
        ).toBe('every Friday at 5:00 PM, March to October');
        expect(
            describeSchedule({
                frequency: 'month',
                hour: 9,
                minute: 0,
                dayOfMonth: 1,
                monthStart: 3,
                monthEnd: 10,
            })
        ).toBe('on the 1st of each month at 9:00 AM, March to October');
    });

    it('is unchanged for plain schedules, and full ranges say nothing', () => {
        expect(describeSchedule({ frequency: 'minutes', interval: 30 })).toBe(
            'every 30 minutes'
        );
        expect(describeSchedule({ frequency: 'day', hour: 9, minute: 0 })).toBe(
            'daily at 9:00 AM'
        );
        expect(
            describeSchedule({
                frequency: 'minutes',
                interval: 30,
                monthDayStart: 1,
                monthDayEnd: 31,
                monthStart: 1,
                monthEnd: 12,
            })
        ).toBe('every 30 minutes');
    });

    it('ignores unparseable window values (unresolved {{refs}})', () => {
        expect(
            describeSchedule({
                frequency: 'minutes',
                interval: 30,
                windowStart: '{{form.values.start}}',
                windowEnd: '18:00',
            })
        ).toBe('every 30 minutes');
    });
});

describe('describeDays', () => {
    it('treats empty and all-seven as every day', () => {
        expect(describeDays(undefined)).toBe('');
        expect(describeDays([])).toBe('');
        expect(describeDays([0, 1, 2, 3, 4, 5, 6])).toBe('');
    });

    it('recognizes the presets', () => {
        expect(describeDays([1, 2, 3, 4, 5])).toBe('on weekdays');
        expect(describeDays([0, 6])).toBe('on weekends');
        expect(describeDays([5, 1, 3])).toBe('on Mon, Wed, Fri');
    });
});

describe('pill labels', () => {
    it('windowLabel formats or stays empty', () => {
        expect(windowLabel({ windowStart: '09:00', windowEnd: '18:00' })).toBe(
            '9:00 AM – 6:00 PM'
        );
        expect(windowLabel({})).toBe('');
        expect(
            windowLabel({ windowStart: '{{ref}}', windowEnd: '18:00' })
        ).toBe('');
    });

    it('daysLabel is the bare form of describeDays', () => {
        expect(daysLabel([1, 2, 3, 4, 5])).toBe('weekdays');
        expect(daysLabel([0, 6])).toBe('weekends');
        expect(daysLabel(undefined)).toBe('');
    });

    it('calendarLabel collapses points and combines dimensions', () => {
        expect(calendarLabel({ monthStart: 8, monthEnd: 8 })).toBe('August');
        expect(calendarLabel({ monthStart: 3, monthEnd: 10 })).toBe(
            'March – October'
        );
        expect(calendarLabel({ monthDayStart: 10, monthDayEnd: 10 })).toBe(
            '10th of each month'
        );
        expect(calendarLabel({ monthDayStart: 10, monthDayEnd: 15 })).toBe(
            '10th – 15th of each month'
        );
        expect(
            calendarLabel({
                monthDayStart: 10,
                monthDayEnd: 15,
                monthStart: 8,
                monthEnd: 8,
            })
        ).toBe('10th – 15th of August');
        expect(
            calendarLabel({
                monthDayStart: 10,
                monthDayEnd: 15,
                monthStart: 3,
                monthEnd: 10,
            })
        ).toBe('10th – 15th, March – October');
        expect(calendarLabel({})).toBe('');
        expect(
            calendarLabel({
                monthDayStart: 1,
                monthDayEnd: 31,
                monthStart: 1,
                monthEnd: 12,
            })
        ).toBe('');
    });
});

describe('isTimeOfDaySchedule', () => {
    it('every narrowing constraint makes timezone meaningful for intervals', () => {
        expect(
            isTimeOfDaySchedule({ frequency: 'minutes', interval: 30 })
        ).toBe(false);
        expect(
            isTimeOfDaySchedule({
                frequency: 'minutes',
                interval: 30,
                windowStart: '09:00',
                windowEnd: '18:00',
            })
        ).toBe(true);
        expect(
            isTimeOfDaySchedule({
                frequency: 'minutes',
                interval: 30,
                daysOfWeek: [1],
            })
        ).toBe(true);
        expect(
            isTimeOfDaySchedule({
                frequency: 'minutes',
                interval: 30,
                monthDayStart: 1,
                monthDayEnd: 15,
            })
        ).toBe(true);
        expect(
            isTimeOfDaySchedule({
                frequency: 'seconds',
                interval: 10,
                monthStart: 3,
                monthEnd: 10,
            })
        ).toBe(true);
        expect(isTimeOfDaySchedule({ frequency: 'day' })).toBe(true);
    });
});
