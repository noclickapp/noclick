// @vitest-environment happy-dom
// An agents page's agent in its channel, over Work's lab world: its first message says what it needs with a Connect
// for each, each a tick once it's in; then its hello, with first tasks to tap.
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { afterEach, describe, expect, it } from 'vitest';
import { answerSessions } from '../lab/sessions';
import { SCENES } from '../lab/scenes';
import { SceneView } from '../lab/WorkLab';

afterEach(cleanup);

function open(id: string) {
    const scene = SCENES.find((s) => s.id === id)!;
    const router = createMemoryRouter([{ path: '*', element: <SceneView scene={scene} actsAs="owner" site="https://noclick.test" prepare={answerSessions} /> }], {
        initialEntries: [`/work?${new URLSearchParams(scene.place)}`],
    });
    render(<RouterProvider router={router} />);
}

describe('an agents page’s agent in its channel', () => {
    it('asks for what it needs, each to connect from its message', async () => {
        open('agent-for-apps-waiting');
        const asks = await screen.findByTestId('message-asks');
        await waitFor(() => expect(within(asks).getByRole('button', { name: 'Connect Roblox' }).hasAttribute('disabled')).toBe(false));
        expect(within(asks).getByRole('button', { name: 'Connect a model' })).toBeTruthy();
        expect(screen.getByText(/I need two things before I can start/)).toBeTruthy();
    });

    it('once both are in, ticks them off and says hello with first tasks to tap', async () => {
        open('agent-for-apps-ready');
        const asks = await screen.findByTestId('message-asks');
        await waitFor(() => expect(within(asks).getByText('Roblox connected')).toBeTruthy());
        expect(within(asks).getByText('Model connected')).toBeTruthy();
        expect(within(asks).queryByRole('button')).toBeNull();
        const taps = screen.getByRole('group', { name: 'Answers' });
        expect(within(taps).getAllByRole('button').map((b) => b.textContent)).toEqual(['Show my experience', 'Show my data stores']);
    });
});
