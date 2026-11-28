// @vitest-environment happy-dom
// A space's Automations look and work as the Automations page does, over Work's fixtures: its cards draw each one's
// graph, with what's the space's own on each (how its last run went, when it runs next, what people here get of it, Run
// now), the page's toggle draws them as its rows instead, and opening one opens its canvas, as the page does. New
// automation makes one by hand as the page's New does, shared with the space as it's made, or asks NoClick.
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { afterEach, expect, it, vi } from 'vitest';
import type { WorkContextValue } from '../../context';
import { SCENES } from '../../lab/scenes';
import { answerSessions } from '../../lab/sessions';
import { SceneView } from '../../lab/WorkLab';

afterEach(() => {
    cleanup();
    localStorage.clear();
});

function open(id: string, work: WorkContextValue) {
    const scene = SCENES.find((s) => s.id === id)!;
    const calls: string[] = [];
    const router = createMemoryRouter(
        [{ path: '*', element: <SceneView scene={scene} actsAs="owner" site="https://noclick.test" work={work} prepare={answerSessions} observe={(method, path) => calls.push(`${method} ${path}`)} /> }],
        { initialEntries: [`/work?${new URLSearchParams(scene.place)}`] }
    );
    render(<RouterProvider router={router} />);
    return { router, calls };
}

it('draws each as the Automations page’s card, with its runs and what people here get, and opens it on its canvas', async () => {
    const openWorkflow = vi.fn();
    open('resources-automations', { openWorkflow });
    const grid = await screen.findByTestId('space-automations-grid');
    const plan = await within(grid).findByTestId('automation-wf_monday_plan');
    const digest = within(grid).getByTestId('automation-wf_weekly_digest');

    // Each card is a picture of its graph, then its name and what it does.
    expect(plan.querySelectorAll('svg rect').length).toBeGreaterThanOrEqual(3);
    expect(plan.textContent).toContain('Every Monday, plans the week’s posts and schedules them on Instagram.');
    // How it last ran and when it runs next (why it failed in their tooltip), and what everyone here gets of it.
    expect(within(plan).getByText('Failed 4d ago')).toBeTruthy();
    expect(within(plan).getByTitle('Failed 4d ago: Instagram isn’t connected · Next in 3d')).toBeTruthy();
    expect(within(plan).getByTitle('Everyone here: run')).toBeTruthy();
    expect(within(digest).getByTitle('Ran 20h ago · Next tomorrow')).toBeTruthy();
    expect(within(digest).getByTitle('Everyone here: see runs')).toBeTruthy();
    // Run now runs it where it is; the card itself opens its canvas.
    fireEvent.click(within(plan).getByRole('button', { name: 'Run Monday plan now' }));
    expect(openWorkflow).not.toHaveBeenCalled();
    fireEvent.click(plan);
    expect(openWorkflow).toHaveBeenCalledWith({ id: 'wf_monday_plan', name: 'Monday plan' });

    // The page's toggle draws them as its rows, remembered for the next space.
    fireEvent.click(screen.getByRole('button', { name: 'List view' }));
    const row = await screen.findByTestId('automation-wf_monday_plan');
    expect(screen.queryByTestId('space-automations-grid')).toBeNull();
    expect(row.textContent).toMatch(/Monday plan.*Failed 4d ago · Next in 3d/);
    expect(localStorage.getItem('noclick:workflows:spaces:browserLayoutMode')).toBe('list');
});

it('makes a blank one as the Automations page’s New does, shares it with the space and opens its canvas', async () => {
    const openWorkflow = vi.fn();
    const ask = vi.fn();
    const { calls } = open('resources-automations', { openWorkflow, ask });
    fireEvent.click(await screen.findByRole('button', { name: 'New automation' }));
    const dialog = await screen.findByRole('dialog');
    // Asking NoClick is the other way.
    expect(within(dialog).getByRole('button', { name: 'Ask NoClick' })).toBeTruthy();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Open a blank canvas' }));

    await waitFor(() => expect(openWorkflow).toHaveBeenCalledWith({ id: expect.stringMatching(/^wf_new_/), name: 'Untitled' }));
    expect(calls.filter((c) => c.startsWith('POST /v1/workflows') || c.startsWith('POST /v1/workspaces'))).toEqual(['POST /v1/workflows', 'POST /v1/workspaces/ws_noclick/resources']);
    expect(ask).not.toHaveBeenCalled();
    // Shared with everyone here as it's made: the space lists it.
    const made: { id: string } = openWorkflow.mock.calls[0][0];
    expect(await screen.findByTestId(`automation-${made.id}`)).toBeTruthy();
    expect(screen.queryByRole('dialog')).toBeNull();
});
