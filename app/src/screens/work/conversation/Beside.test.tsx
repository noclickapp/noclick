// @vitest-environment happy-dom
// Work's Beside draws status the way the agent's ring does, wherever it shows (Work's conversations and the Chat page):
// ink for what runs and what needs you, red only for a failure, never green. What else needs the person (`asks`) leads
// the card and the rail, each with its one action, its title going where the conversation shows it.
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import type { ReactNode } from 'react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { TooltipProvider } from '@/ui/tooltip';
import { BesideCard, BesideRail, type BesideAsk } from './Beside';
import { agentItem, type BesideItem } from './besideItems';
import type { Operation } from 'noclick';

afterEach(cleanup);

function item(id: string, status: BesideItem['status']): BesideItem {
    return { id, kind: 'agent', title: `Task ${id}`, status, startedAt: Date.now() - 60_000, endedAt: status === 'running' || status === 'needs' ? null : Date.now(), activeAt: Date.now(), line: `Line ${id}`, call: null, turnRunning: false, agent: { agentId: id, name: id, task: `Task ${id}`, jobId: null }, spendUsd: null };
}

function draw(node: ReactNode) {
    const router = createMemoryRouter([{ path: '*', element: <TooltipProvider>{node}</TooltipProvider> }]);
    return render(<RouterProvider router={router} />);
}

const ITEMS = [item('run', 'running'), item('wait', 'needs'), item('fail', 'failed'), item('done', 'done')];

describe('Work’s Beside', () => {
    it('marks status in ink, red only for a failure, never green', () => {
        draw(<BesideRail items={ITEMS} facts={null} face={{ id: 'main', kind: 'agent', name: 'Main' }} look={() => ({ harness: null, runsOn: null })} selected={null} onSelect={() => undefined} stoppable={() => false} onStop={() => undefined} fresh={new Set()} />);
        const rail = screen.getByTestId('beside-rail');
        fireEvent.click(within(rail).getByRole('button', { name: /Done today/ }));
        // The agent's own ring: the shimmer while it runs, solid ink when it needs you, red when it failed.
        const ring = (id: string) => rail.querySelector(`[data-beside="${id}"] [data-ring] [data-ring]`)?.getAttribute('data-ring');
        expect(ring('run')).toBe('working');
        expect(ring('wait')).toBe('needs');
        expect(ring('fail')).toBe('failed');
        expect(rail.innerHTML).not.toMatch(/emerald|green-/);
        // What needs you heads its group in ink, its line too.
        expect(within(rail).getByText('Needs you').className).not.toMatch(/red/);
        expect(rail.querySelector('[data-beside="wait"]')!.innerHTML).not.toMatch(/red-/);
        expect(rail.querySelector('[data-beside="fail"]')!.innerHTML).toMatch(/red-/);
    });

    it('counts what needs you in ink on the card, and leads it with the asks', () => {
        const jumped = vi.fn();
        const reviewed = vi.fn();
        const asks: BesideAsk[] = [
            { key: 'buy', title: 'Buy morrow.com?', line: '$11.25 a year', action: { label: 'Review', onClick: reviewed }, onJump: jumped },
            { key: 'stripe', title: 'Morrow Bakehouse', line: 'Waiting for you to connect Stripe', action: { label: 'Connect Stripe', href: 'https://noclick.com/credential/provide/x' } },
            { key: 'cap', title: 'Monthly cap reached', line: null, action: { label: 'Raise cap', href: '/dashboard?tab=settings&section=billing' } },
        ];
        draw(<BesideCard facts={null} items={[item('run', 'running')]} asks={asks} onOpen={() => undefined} />);
        const card = screen.getByTestId('beside-card');
        const needs = within(card).getByTestId('beside-needs');
        expect(needs.textContent).toMatch(/^Needs you3/);
        // Review is done here, not on a page of its own.
        expect(within(needs).queryByRole('link', { name: 'Review' })).toBeNull();
        fireEvent.click(within(needs).getByRole('button', { name: 'Review' }));
        expect(reviewed).toHaveBeenCalledOnce();
        // An account to connect is connected where its link goes, in a tab of its own.
        const connect = within(needs).getByRole('link', { name: 'Connect Stripe' });
        expect([connect.getAttribute('href'), connect.getAttribute('target')]).toEqual(['https://noclick.com/credential/provide/x', '_blank']);
        fireEvent.click(within(needs).getByRole('button', { name: /Buy morrow\.com\?/ }));
        expect(jumped).toHaveBeenCalledOnce();
        expect(reviewed).toHaveBeenCalledOnce();
        // A page of this app opens in place.
        const raise = within(needs).getByRole('link', { name: 'Raise cap' });
        expect([raise.getAttribute('href'), raise.getAttribute('target')]).toEqual(['/dashboard?tab=settings&section=billing', null]);
        // An ask with nowhere to go has a title that goes nowhere.
        expect((within(needs).getByRole('button', { name: /Monthly cap/ }) as HTMLButtonElement).disabled).toBe(true);
        // Helpers below them, counted with ink dots.
        expect(card.textContent).toContain('Beside it1 running');
        expect(card.innerHTML).not.toMatch(/emerald|red-/);
    });

    it('names the workstream a NoClick agent’s task belongs to on its card, as its operation names it', async () => {
        const started = { child: { agentId: 'pages', name: 'morrow-pages', task: 'Write the pages', jobId: 'op-pages' }, step: { at: Date.now() - 60_000 } } as Parameters<typeof agentItem>[0];
        const job = { id: 'op-pages', status: 'running', workstream: { id: 'ws-launch', name: 'Spring launch' }, startedAt: null, createdAt: null, finishedAt: null, result: null } as unknown as Operation;
        const named = agentItem(started, job, undefined, null);
        expect(named.workstream).toBe('Spring launch');
        expect(agentItem(started, { ...job, workstream: null } as unknown as Operation, undefined, null).workstream).toBeNull();
        draw(<BesideRail items={[named]} facts={null} face={{ id: 'main', kind: 'agent', name: 'Main' }} look={() => ({ harness: null, runsOn: null })} selected={null} onSelect={() => undefined} stoppable={() => false} onStop={() => undefined} fresh={new Set()} />);
        fireEvent.focus(within(screen.getByTestId('beside-rail')).getByRole('button', { name: 'Write the pages: Running' }));
        const card = await screen.findByRole('tooltip');
        expect(card.textContent).toContain('WorkstreamSpring launch');
    });
});
