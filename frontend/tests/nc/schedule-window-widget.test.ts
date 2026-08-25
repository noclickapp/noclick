// Renders the real ScheduleWidget (detached — touches no workflow) inside the
// live app and smoke-checks the sentence-pill UX: unconstrained words, the
// constrained stacked labels + summary, a popover edit, and frequency pruning.
// Headless twin: tests/components/ScheduleWidget.test.tsx (full coverage).
import React from 'react';
import { createRoot } from 'react-dom/client';
import {
    ScheduleWidget,
    type ScheduleConfig,
} from '~/components/workflow/ScheduleWidget';

const settle = () =>
    new Promise<void>((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(() => resolve()))
    );

export default async function () {
    const host = document.createElement('div');
    document.body.appendChild(host);
    const root = createRoot(host);
    const captured: { latest: ScheduleConfig | null } = { latest: null };
    const latest = (): ScheduleConfig | null => captured.latest;

    const render = async (value: ScheduleConfig) => {
        root.render(
            React.createElement(ScheduleWidget, {
                value,
                showWindow: true,
                onChange: (v: ScheduleConfig) => {
                    captured.latest = v;
                },
            })
        );
        await settle();
    };

    const button = (text: string) =>
        [...host.querySelectorAll('button')].find(
            (b) => b.textContent?.trim() === text
        );

    // Popovers/menus portal into document.body, which in the live app already
    // holds the page's own selects/buttons — query by diff against a snapshot
    // taken before opening.
    const snapshot = <T extends Element>(sel: string) =>
        new Set(document.body.querySelectorAll(sel)) as Set<T>;
    const appeared = <T extends Element>(sel: string, before: Set<T>) =>
        [...document.body.querySelectorAll(sel)].filter(
            (el) => !before.has(el as T)
        ) as T[];

    try {
        // Plain interval schedule: the unconstrained sentence words render.
        await render({ frequency: 'minutes', interval: 5 });
        for (const word of ['all day', 'every day', 'all year']) {
            if (!button(word)) throw new Error(`pill "${word}" missing`);
        }

        // Clicking "all day" COMMITS the 9–6 starting window (what the
        // popover shows is what is set) and opens it for adjustment.
        const beforeSelects = snapshot<HTMLSelectElement>('select');
        button('all day')!.click();
        await settle();
        if (
            latest()?.windowStart !== '09:00' ||
            latest()?.windowEnd !== '18:00'
        ) {
            throw new Error(
                `opening the time pill must commit the window: ${JSON.stringify(latest())}`
            );
        }
        const selects = appeared<HTMLSelectElement>('select', beforeSelects);
        if (selects.length !== 2)
            throw new Error(`expected 2 time selects, got ${selects.length}`);
        selects[1].value = '17:00';
        selects[1].dispatchEvent(new Event('change', { bubbles: true }));
        await settle();
        if (
            latest()?.windowStart !== '09:00' ||
            latest()?.windowEnd !== '17:00'
        ) {
            throw new Error(
                `time edit did not apply: ${JSON.stringify(latest())}`
            );
        }

        // Stacked config: constrained labels + the prose summary.
        await render({
            frequency: 'minutes',
            interval: 30,
            windowStart: '09:00',
            windowEnd: '18:00',
            daysOfWeek: [1, 2, 3, 4, 5],
            monthDayStart: 1,
            monthDayEnd: 15,
            monthStart: 3,
            monthEnd: 10,
        });
        const text = host.textContent || '';
        for (const expected of [
            '9:00 AM – 6:00 PM',
            'weekdays',
            '1st – 15th, March – October',
            'Runs every 30 minutes from 9:00 AM to 6:00 PM on weekdays, the 1st–15th of each month, March to October',
        ]) {
            if (!text.includes(expected))
                throw new Error(`missing "${expected}" in: ${text}`);
        }

        // Frequency switch prunes what daily can't carry, keeps what it can.
        const beforeMenu = snapshot<HTMLButtonElement>('button[data-index]');
        button('minutes')!.click();
        await settle();
        const dayOption = appeared<HTMLButtonElement>(
            'button[data-index]',
            beforeMenu
        ).find((b) => b.textContent?.trim() === 'day');
        if (!dayOption) throw new Error('day frequency option not found');
        dayOption.click();
        await settle();
        const pruned = latest() as ScheduleConfig;
        if (
            pruned.windowStart !== undefined ||
            pruned.windowEnd !== undefined
        ) {
            throw new Error(`window not pruned: ${JSON.stringify(pruned)}`);
        }
        if (pruned.monthStart !== 3 || pruned.monthDayStart !== 1) {
            throw new Error(
                `calendar constraints must survive daily: ${JSON.stringify(pruned)}`
            );
        }

        return { ok: true };
    } finally {
        root.unmount();
        host.remove();
    }
}
