// @vitest-environment happy-dom
// The card under an agents page's arrival note, over the Chat lab's world (the chat's fake /v1): the agent, where it
// runs and where you talk to it, then what it still needs, each with a white Connect; once everything is in, Open
// #roblox is the white pill and a box under it posts into the channel as you.
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { afterEach, describe, expect, it } from 'vitest';
import { PILL_PRIMARY } from '@/ui/chat/primitives';
import { SceneView } from '../lab/ChatLab';
import { SCENES, sceneSearch } from '../lab/scenes';

afterEach(cleanup);

function open(id: string) {
    const scene = SCENES.find((s) => s.id === id)!;
    const calls: string[] = [];
    const router = createMemoryRouter([{ path: '*', element: <SceneView scene={scene} actsAs="owner" site="https://noclick.test" observe={(method, path) => void calls.push(`${method} ${path}`)} /> }], {
        initialEntries: [`/chat-lab${sceneSearch(scene)}`],
    });
    render(<RouterProvider router={router} />);
    return calls;
}

const primary = (button: HTMLElement) => button.className === PILL_PRIMARY;

describe('the card of an agent an agents page made', () => {
    it('waits on its app and its model, each with Connect', async () => {
        open('agent-for-apps-waiting');
        const card = await screen.findByTestId('agent-for-apps-card');
        await waitFor(() => expect(within(card).getByText('Runs on Hermes · in #roblox, your personal space')).toBeTruthy());
        expect(within(card).getByText('2 to connect')).toBeTruthy();
        const app = within(card).getByTestId('agent-for-apps-need-app');
        expect(within(app).getByText('Roblox')).toBeTruthy();
        const model = within(card).getByTestId('agent-for-apps-need-model');
        expect(within(model).getByText('A model for Hermes')).toBeTruthy();
        for (const row of [app, model]) expect(primary(within(row).getByRole('button', { name: /^Connect/ }))).toBe(true);
        // Its channel opens from here, quietly, until it can start; there's nothing to tell it yet.
        expect(primary(within(card).getByTestId('agent-for-apps-open'))).toBe(false);
        expect(within(card).queryByRole('textbox')).toBeNull();
    });

    it('once everything is in, opens its channel and posts there as you', async () => {
        const calls = open('agent-for-apps-ready');
        const card = await screen.findByTestId('agent-for-apps-card');
        await waitFor(() => expect(within(card).getByText('Ready')).toBeTruthy());
        expect(within(card).getAllByText('Connected')).toHaveLength(2);
        expect(within(card).getByText('Runs on your OpenRouter key')).toBeTruthy();
        expect(primary(within(card).getByTestId('agent-for-apps-open'))).toBe(true);
        const box = within(card).getByRole('textbox', { name: 'Tell Roblox agent what to work on' });
        fireEvent.change(box, { target: { value: 'Show me my data stores' } });
        fireEvent.submit(box.closest('form')!);
        await waitFor(() => expect(calls).toContain('POST /v1/channels/ch_roblox/messages'));
    });
});
