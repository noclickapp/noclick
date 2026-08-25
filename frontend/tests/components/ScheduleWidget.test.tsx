// @vitest-environment jsdom
// Renders the real ScheduleWidget and verifies the sentence-pill UX: every
// narrowing dimension is an always-visible inline word ("all day · every day
// · all year") that opens a popover; pills adapt to frequency, clear
// semantically, and prune on frequency switches. Headless twin of
// tests/nc/schedule-window-widget.test.ts (which runs inside the live app).
import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import React from 'react';
import {
    ScheduleWidget,
    type ScheduleConfig,
} from '~/components/workflow/ScheduleWidget';

afterEach(cleanup);

// jsdom has no scrollIntoView; the dropdown's highlight-scroll effect uses it.
window.HTMLElement.prototype.scrollIntoView = () => {};

const STACKED: ScheduleConfig = {
    frequency: 'minutes',
    interval: 30,
    windowStart: '09:00',
    windowEnd: '18:00',
    daysOfWeek: [1, 2, 3, 4, 5],
    monthDayStart: 1,
    monthDayEnd: 15,
    monthStart: 3,
    monthEnd: 10,
};

function renderWidget(value: ScheduleConfig) {
    let latest: ScheduleConfig | null = null;
    const utils = render(
        <ScheduleWidget
            value={value}
            showWindow
            onChange={(v) => {
                latest = v;
            }}
        />
    );
    return { ...utils, latest: () => latest };
}

describe('ScheduleWidget sentence pills', () => {
    it('shows the unconstrained sentence words for a plain interval schedule', () => {
        renderWidget({ frequency: 'minutes', interval: 5 });
        expect(screen.getByText('all day')).toBeTruthy();
        expect(screen.getByText('every day')).toBeTruthy();
        expect(screen.getByText('all year')).toBeTruthy();
    });

    it('shows constrained labels + the prose summary for a stacked config', () => {
        renderWidget(STACKED);
        expect(screen.getByText('9:00 AM – 6:00 PM')).toBeTruthy();
        expect(screen.getByText('weekdays')).toBeTruthy();
        expect(screen.getByText('1st – 15th, March – October')).toBeTruthy();
        expect(
            screen.getByText(
                'Runs every 30 minutes from 9:00 AM to 6:00 PM on weekdays, the 1st–15th of each month, March to October'
            )
        ).toBeTruthy();
    });

    it('time pill: opening commits the starting window; selects adjust; "All day" clears', () => {
        const { latest } = renderWidget({ frequency: 'minutes', interval: 30 });
        fireEvent.click(screen.getByText('all day'));
        // Opening COMMITS 9–6 immediately — what the popover shows is what is
        // set, never a prefilled suggestion that looks applied but isn't.
        expect(latest()).toMatchObject({
            windowStart: '09:00',
            windowEnd: '18:00',
        });
        const selects = document.body.querySelectorAll('select');
        expect(selects).toHaveLength(2);
        fireEvent.change(selects[1], { target: { value: '17:00' } });
        expect(latest()).toMatchObject({
            windowStart: '09:00',
            windowEnd: '17:00',
        });

        // Constrained pill offers the semantic clear.
        cleanup();
        const second = renderWidget({
            frequency: 'minutes',
            interval: 30,
            windowStart: '09:00',
            windowEnd: '17:00',
        });
        fireEvent.click(screen.getByText('9:00 AM – 5:00 PM'));
        fireEvent.click(screen.getByText('All day'));
        expect(second.latest()!.windowStart).toBeUndefined();
        expect(second.latest()!.windowEnd).toBeUndefined();
    });

    it('days pill: stringified entries still highlight chips and unselect (AI-builder writes)', () => {
        // Live-repro'd config: string entries + a stranded duplicate from a
        // mixed-type toggle. Chips must still show selection, and clicking a
        // selected day must REMOVE it, writing clean numbers back.
        const { latest } = renderWidget({
            frequency: 'minutes',
            interval: 30,
            daysOfWeek: ['1', '1', '2', '3'],
        });
        expect(screen.getByText('Mon, Tue, Wed')).toBeTruthy();
        fireEvent.click(screen.getByText('Mon, Tue, Wed'));
        const monday = screen.getByTitle('Monday');
        // Selected chip is visually marked.
        expect(monday.className).toContain('bg-primary');
        fireEvent.click(monday);
        expect(latest()!.daysOfWeek).toEqual([2, 3]);
    });

    it('days pill: chips toggle, presets set and clear', () => {
        const { latest } = renderWidget({ frequency: 'minutes', interval: 30 });
        fireEvent.click(screen.getByText('every day'));
        fireEvent.click(screen.getByText('Weekdays'));
        expect(latest()!.daysOfWeek).toEqual([1, 2, 3, 4, 5]);

        cleanup();
        const withDays = renderWidget({
            frequency: 'minutes',
            interval: 30,
            daysOfWeek: [1, 2, 3, 4, 5],
        });
        fireEvent.click(screen.getByText('weekdays'));
        fireEvent.click(screen.getByTitle('Saturday'));
        expect(withDays.latest()!.daysOfWeek).toEqual([1, 2, 3, 4, 5, 6]);
        fireEvent.click(screen.getByText('Every day'));
        expect(withDays.latest()!.daysOfWeek).toBeUndefined();
    });

    it('calendar pill: picking a month collapses to the point form, "through" makes a range', () => {
        const { latest } = renderWidget({
            frequency: 'day',
            hour: 9,
            minute: 0,
        });
        fireEvent.click(screen.getByText('all year'));
        // day frequency: both groups shown (days of month + months).
        const selects = () => [...document.body.querySelectorAll('select')];
        expect(selects()).toHaveLength(2); // "Any day" + "All year" (no range partners yet)
        fireEvent.change(selects()[1], { target: { value: '8' } });
        expect(latest()).toMatchObject({ monthStart: 8, monthEnd: 8 });

        cleanup();
        const august = renderWidget({
            frequency: 'day',
            hour: 9,
            minute: 0,
            monthStart: 8,
            monthEnd: 8,
        });
        expect(screen.getByText('August')).toBeTruthy();
        fireEvent.click(screen.getByText('August'));
        const monthSelects = [...document.body.querySelectorAll('select')];
        // "Any day" group + months group now has its "through" partner.
        expect(monthSelects).toHaveLength(3);
        fireEvent.change(monthSelects[2], { target: { value: '10' } });
        expect(august.latest()).toMatchObject({ monthStart: 8, monthEnd: 10 });
    });

    it('adapts pills to the frequency', () => {
        renderWidget({ frequency: 'day', hour: 9, minute: 0 });
        expect(screen.queryByText('all day')).toBeNull(); // no time window on daily
        expect(screen.getByText('every day')).toBeTruthy();
        expect(screen.getByText('all year')).toBeTruthy();

        cleanup();
        renderWidget({ frequency: 'week', dayOfWeek: 5, hour: 17, minute: 0 });
        expect(screen.queryByText('all day')).toBeNull();
        expect(screen.queryByText('every day')).toBeNull();
        expect(screen.getByText('all year')).toBeTruthy();
        // Weekly calendar popover offers months only.
        fireEvent.click(screen.getByText('all year'));
        expect(document.body.querySelectorAll('select')).toHaveLength(1);

        cleanup();
        renderWidget({
            frequency: 'weeks',
            interval: 2,
            dayOfWeek: 1,
            hour: 9,
            minute: 0,
        });
        expect(screen.queryByText('all year')).toBeNull(); // nothing applies
    });

    it('switching frequency prunes constraints the new frequency cannot carry', () => {
        const { latest } = renderWidget(STACKED);
        fireEvent.click(screen.getByText('minutes'));
        fireEvent.click(
            [...document.body.querySelectorAll('button[data-index]')].find(
                (b) => b.textContent?.trim() === 'day'
            )!
        );
        const pruned = latest()!;
        expect(pruned.windowStart).toBeUndefined();
        expect(pruned.windowEnd).toBeUndefined();
        // day supports these — they must survive.
        expect(pruned.daysOfWeek).toEqual([1, 2, 3, 4, 5]);
        expect(pruned.monthDayStart).toBe(1);
        expect(pruned.monthStart).toBe(3);
    });

    it('shows no pills at all without showWindow', () => {
        render(
            <ScheduleWidget
                value={{ frequency: 'minutes', interval: 5 }}
                onChange={() => {}}
            />
        );
        expect(screen.queryByText('all day')).toBeNull();
        expect(screen.queryByText('every day')).toBeNull();
    });
});
