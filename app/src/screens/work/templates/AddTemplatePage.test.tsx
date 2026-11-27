// @vitest-environment happy-dom
// A space template's page of asks in Work, over Work's fixtures: as a new space it lists what comes under the
// template's own names, what it costs a month and the cap its agents stop at, each account (one you have shown as
// connected) and each key; into a space you have, a tick on each part, the channels under the template's word, and
// unticking leaves a part out of what's added. One tap adds it, and Work lands on the space's #noclick, where the welcome
// post asks for what's left and offers a first task posted where its agent works.
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { afterEach, expect, it } from 'vitest';
import { SCENES } from '../lab/scenes';
import { answerSessions } from '../lab/sessions';
import { SceneView } from '../lab/WorkLab';
import type { Observe } from '../lab/worlds';

afterEach(cleanup);

function open(id: string) {
    const scene = SCENES.find((s) => s.id === id)!;
    const sent: { method: string; path: string }[] = [];
    const observe: Observe = (method, path) => sent.push({ method, path });
    const router = createMemoryRouter([{ path: '*', element: <SceneView scene={scene} actsAs="owner" site="https://noclick.test" prepare={answerSessions} observe={observe} /> }], {
        initialEntries: [`/work?${new URLSearchParams(scene.place)}`],
    });
    render(<RouterProvider router={router} />);
    return { router, sent };
}

/** Each part's row: its name, then its line. */
const rows = () => within(screen.getByTestId('template-parts')).getAllByRole('listitem').map((li) => [...li.querySelectorAll('p')].map((p) => p.textContent).join(' | '));

it('reads a template as a new space: its parts, what it costs, its cap, its accounts and keys, then adds it', async () => {
    const { router, sent } = open('template-new');
    expect(await screen.findByRole('heading', { name: 'Social media team' })).toBeTruthy();
    expect(screen.getByText('A template from')).toBeTruthy();
    expect(rows().slice(0, 4)).toEqual([
        'Writer | Plans and drafts posts in the brand’s voice',
        'Designer | Makes the images · needs Canva',
        'Scheduler | Posts at the best times · needs Instagram, LinkedIn and X',
        '#ideas | Writer',
    ]);
    // No ticks on a new space: everything comes.
    expect(within(screen.getByTestId('template-parts')).queryAllByRole('checkbox')).toHaveLength(0);
    const cost = screen.getByTestId('template-cost').textContent;
    expect(cost).toContain('~$0.67a month, by what it uses, and its agents up to $40');
    expect(cost).toContain('Its agentsWriter, Designer and Scheduler, by what they doup to $40');
    expect((screen.getByTestId('template-cap') as HTMLInputElement).value).toBe('40');
    const accounts = screen.getByTestId('template-accounts').textContent;
    expect(accounts).toContain('LinkedInRowan’s LinkedIn Connected');
    expect(accounts).toContain('Connect now or later: what’s left waits in the space’s #noclick.');
    expect(screen.getByText('UNSPLASH_ACCESS_KEY')).toBeTruthy();

    fireEvent.click(screen.getByTestId('template-add'));
    expect((await screen.findByTestId('template-adding')).textContent).toContain('Building and deploying its app');
    // Its operation's frame says it's done: Work opens the new space's #noclick, on the welcome post.
    await waitFor(() => expect(router.state.location.search).toContain('channel=ch_social_noclick'), { timeout: 5000 });
    expect(await screen.findByText(/Rowan added Social media team/)).toBeTruthy();
    expect(screen.getByTestId('channel-asks').textContent).toContain('Canva');
    expect(sent.filter((s) => s.path === '/v1/workspaces/from_template').length).toBeGreaterThanOrEqual(2);
});

it('into a space you have, ticks each part, names its channels with the template’s word, and leaves out what’s unticked', async () => {
    open('template-into');
    expect(await screen.findByText('#social-ideas')).toBeTruthy();
    expect(rows()).toContain('Social Writer | Plans and drafts posts in the brand’s voice');
    expect(rows()).toContain('#social-drafts | Social Writer and Designer');
    expect(screen.getByTestId('template-add').textContent).toBe('Add to NoClick');
    fireEvent.click(screen.getByRole('checkbox', { name: 'Bring content-calendar' }));
    // The dry run is read again without the app: nothing of its hosting is left to pay.
    await waitFor(() => expect(screen.getByTestId('template-cost').textContent).toContain('$0a month, by what it uses'));
});
