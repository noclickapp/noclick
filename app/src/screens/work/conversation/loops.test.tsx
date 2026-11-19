// @vitest-environment happy-dom
// A conversation's loops, wherever its box and its Beside are (Work and the Chat page): /loop is NoClick's own command
// with what follows it, its answer said plainly, and each loop a Beside row that says how it comes round and when it
// runs next, with a Stop and nothing to open.
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Wakeup, type CommandResult } from 'noclick';
import { TooltipProvider } from '@/ui/tooltip';
import { BesideRail, StopBeside } from './Beside';
import { isLoop, loopItem } from './besideItems';
import { loopSaid } from './loops';
import { commandIn, slashCommands } from './menus';

afterEach(cleanup);

const NEXT = new Date(Date.now() + 5 * 60_000).toISOString();

function wakeup(raw: Record<string, unknown>): Wakeup {
    return Wakeup._from({ id: 'wk-1', agent_id: 'ag-1', conversation: 'main', note: 'Check the deploy\nand say if it broke', at: NEXT, every: null, self_paced: false, fired: 3, status: 'pending', error: null, operation_id: 'op-3', created_at: '2026-11-14T08:00:00Z', delivered_at: '2026-11-14T09:55:00Z', ...raw }, {});
}

const result = (r: Record<string, unknown>): CommandResult => ({ control: 'loop', command: { name: 'loop', arguments: '' }, result: r, raw: {} });

describe('/loop', () => {
    it('is NoClick’s own command, and takes what follows it', () => {
        const typed = commandIn(slashCommands(null), '/loop 5m check the deploy');
        expect(typed?.command).toMatchObject({ kind: 'control', control: 'loop' });
        expect(typed?.args).toBe('5m check the deploy');
        // A harness's own /loop goes to NoClick's.
        const listed = slashCommands({ commands: [], skills: [], mapped: [{ name: 'loop', to: 'loop' }], withheld: [], notSupported: {}, asOf: null, readFrom: null, capabilities: {}, harness: 'claude_code', raw: {} } as never);
        expect(listed.filter((c) => c.name === 'loop')).toHaveLength(1);
        // Typed in any box (the Chat page's offers only it of NoClick's own), the same command and what follows it.
        const chat = slashCommands(null, ['loop']);
        expect(chat.map((c) => c.name)).toEqual(['loop']);
        expect(commandIn(chat, '/loop  stop ')?.args).toBe('stop');
        expect(commandIn(chat, '/loop')?.args).toBe('');
        expect(commandIn(chat, '/looped it')).toBeNull();
        expect(commandIn(chat, 'loop 5m')).toBeNull();
    });

    it('says what it started or stopped', () => {
        expect(loopSaid(result({ every: 'every 5 minutes' }), 'Scout')).toBe('Looping every 5 minutes');
        expect(loopSaid(result({ every: 'every 6 minutes', rounded_from: 'every 7 minutes' }), 'Scout')).toBe('Looping every 6 minutes, the nearest a clock keeps to every 7 minutes');
        expect(loopSaid(result({ every: null }), 'Scout')).toBe('Looping: Scout picks when each run comes');
        expect(loopSaid(result({ stopped: 2 }), 'Scout')).toBe('Stopped 2 loops');
        expect(loopSaid(result({ stopped: 0 }), 'Scout')).toBe('No loop was running here');
    });
});

describe('a loop in the Beside', () => {
    it('says how it comes round and when it runs next', () => {
        const every = loopItem(wakeup({ every: { cron: '*/5 * * * *', tz: Intl.DateTimeFormat().resolvedOptions().timeZone } }));
        expect(every).toMatchObject({ kind: 'loop', title: 'Check the deploy', status: 'running', endedAt: null, turnRunning: false, spendUsd: null });
        expect(every.line).toMatch(/^Every 5 minutes · next \d{1,2}:\d{2} [AP]M$/);
        expect(every.loop).toMatchObject({ every: 'Every 5 minutes', runs: 3, nextAt: new Date(NEXT).getTime() });
        // A run of it at work now.
        expect(loopItem(wakeup({ every: { cron: '*/5 * * * *', tz: 'UTC' } }), 'op-3')).toMatchObject({ turnRunning: true });
        // Paced by the agent: while its run works, it has no next time until that run sets one.
        const paced = loopItem(wakeup({ self_paced: true, at: null }));
        expect(paced).toMatchObject({ status: 'running', line: 'Paces itself · running now', turnRunning: true });
        expect(isLoop(wakeup({ self_paced: true }))).toBe(true);
        expect(isLoop(wakeup({}))).toBe(false);
    });

    it('says why once it stopped itself', () => {
        const failed = loopItem(wakeup({ self_paced: true, status: 'failed', error: { type: 'loop_failing', message: 'Its last 3 runs failed.' } }));
        expect(failed).toMatchObject({ status: 'failed', line: 'Its last 3 runs failed.', endedAt: Date.parse('2026-11-14T09:55:00Z') });
        expect(loopItem(wakeup({ self_paced: true, status: 'canceled' })).status).toBe('stopped');
        expect(loopItem(wakeup({ self_paced: true, status: 'delivered' })).status).toBe('done');
    });

    it('is a row with its next run and a Stop, and nothing to open', () => {
        const item = loopItem(wakeup({ every: { cron: '*/5 * * * *', tz: 'UTC' } }));
        const stop = vi.fn();
        const router = createMemoryRouter([
            {
                path: '*',
                element: (
                    <TooltipProvider>
                        <BesideRail items={[item]} facts={null} face={{ id: 'main', kind: 'agent', name: 'Main' }} look={() => ({ harness: null, runsOn: null })} selected={null} onSelect={() => undefined} stoppable={() => true} onStop={stop} fresh={new Set()} title="Beside it" />
                    </TooltipProvider>
                ),
            },
        ]);
        render(<RouterProvider router={router} />);
        const row = screen.getByTestId('beside-rail').querySelector<HTMLElement>('[data-beside="wk-1"]')!;
        expect(within(row).getByTestId('beside-time').textContent).toBe(new Date(NEXT).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' }));
        expect(within(row).queryByRole('button', { name: /Open/ })).toBeNull();
        fireEvent.click(within(row).getByRole('button', { name: 'Stop Check the deploy' }));
        expect(stop).toHaveBeenCalledWith(item);
        // Stopping one is confirmed as a loop's stop.
        render(<StopBeside item={item} onClose={() => undefined} onStop={() => undefined} />);
        expect(screen.getByText('Stop this loop?')).toBeTruthy();
        expect(screen.getByRole('button', { name: 'Stop the loop' })).toBeTruthy();
    });
});
