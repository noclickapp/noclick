// @vitest-environment happy-dom
// Home's Templates in Work, over Work's fixtures and NoClick's own templates as the gallery answers them: a row under
// Threads that stays lit while its page is open, the gallery with its jobs and search, a template's page (the space
// first, its channels switched between, each agent's instructions a tap away), and its button, which opens the page of
// asks aimed at the space you came from.
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { afterEach, expect, it } from 'vitest';
import { SCENES } from '../lab/scenes';
import { answerSessions } from '../lab/sessions';
import { SceneView } from '../lab/WorkLab';

afterEach(cleanup);

function open(id: string) {
    const scene = SCENES.find((s) => s.id === id)!;
    const router = createMemoryRouter([{ path: '*', element: <SceneView scene={scene} actsAs="owner" site="https://noclick.test" prepare={answerSessions} /> }], {
        initialEntries: [`/work?${new URLSearchParams(scene.place)}`],
    });
    render(<RouterProvider router={router} />);
    return router;
}

const cards = () => [...screen.getByTestId('template-gallery').querySelectorAll('[data-template]')].map((c) => c.getAttribute('data-template'));

it('lists the gallery under Threads, filters it by job and words, and opens a template on its page', async () => {
    const router = open('templates');
    const row = await screen.findByTestId('home-templates');
    expect(row.getAttribute('aria-current')).toBe('page');
    await waitFor(() => expect(cards()).toEqual(['social-media-team', 'support-desk', 'inbox-triager', 'launch-page', 'brand-voice']));
    fireEvent.click(screen.getByRole('button', { name: 'Support' }));
    expect(cards()).toEqual(['support-desk']);
    fireEvent.click(screen.getByRole('button', { name: 'All' }));
    fireEvent.change(screen.getByLabelText('Search templates'), { target: { value: 'canva' } });
    expect(cards()).toEqual(['social-media-team']);

    const social = screen.getByTestId('template-gallery').querySelector('[data-template="social-media-team"]')!;
    expect(social.textContent).toContain('3 agents · 3 channels · a skill · a memory');
    expect(social.textContent).toContain('By use, up to $30 a month');
    fireEvent.click(social);
    await waitFor(() => expect(new URLSearchParams(router.state.location.search).get('listing')).toBe('social-media-team'));

    const page = await screen.findByTestId('template-page');
    expect(within(page).getByRole('heading', { level: 1 }).textContent).toBe('Social media team');
    expect(row.getAttribute('aria-current')).toBe('page');
    const preview = within(page).getByTestId('space-preview');
    expect(preview.textContent).toContain('This week: Monday a reel of the new roast');
    fireEvent.click(within(preview).getAllByRole('button', { name: /scheduled/ })[0]);
    expect(preview.textContent).toContain('Booked for Wednesday 12:30');
    expect(within(page).getAllByText('Its instructions')).toHaveLength(3);
    expect(page.textContent).toContain('Writer stops at$10 a month');

    fireEvent.click(within(page).getByTestId('template-add'));
    await waitFor(() => {
        const params = new URLSearchParams(router.state.location.search);
        expect([params.get('template'), params.get('into')]).toEqual([expect.stringContaining('/v1/public/git/'), 'ws_noclick']);
    });
});

it('draws a template with no agents by what it makes: its own screenshots, or its skill', async () => {
    open('templates');
    await waitFor(() => expect(cards()).toHaveLength(5));
    const picture = (slug: string) => screen.getByTestId('template-gallery').querySelector(`[data-template="${slug}"] [data-picture]`)!;
    expect(picture('launch-page').getAttribute('data-picture')).toBe('screenshots');
    expect(picture('launch-page').querySelectorAll('img')).toHaveLength(2);
    expect(picture('brand-voice').getAttribute('data-picture')).toBe('skill');
    expect(picture('brand-voice').textContent).toContain('SKILL.md');
    expect(picture('social-media-team').getAttribute('data-picture')).toBe('faces');
    const launch = screen.getByTestId('template-gallery').querySelector('[data-template="launch-page"]')!;
    expect(launch.textContent).toContain('~$0.67 a month');
    expect(launch.textContent).toContain('Asks for nothing');
});
