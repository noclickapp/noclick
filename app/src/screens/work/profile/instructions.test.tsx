// @vitest-environment happy-dom
// An agent's instructions on its profile, over the fake /v1 through the real SDK: their first lines under its name
// with Show all, Edit and Ask NoClick; the sheet saving an edit on the text it started from; a change NoClick made
// meanwhile shown beside yours rather than overwritten; each version with what it changed; NoClick's own agents
// with no editor.
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { Agent } from 'noclick';
import { WorkContext } from '../context';
import { WorkProviders } from '../agents/fixtures/providers';
import { fakeWork, id } from '../agents/fixtures/workAgents';
import { IN_USE, RACED, RACED_SAID, SAID, digestOf } from './fixtures/instructions';
import { InstructionsUnderName } from './instructions';

beforeEach(() => vi.stubGlobal('fetch', async () => new Response(null, { status: 404 })));
afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
});

async function profile(options: Parameters<typeof fakeWork>[0] = {}, agentId = id(1)) {
    const fake = fakeWork({ coordinator: true, now: Date.now(), ...options });
    const agent = await Agent.get(agentId, { client: fake.client });
    const asked: string[] = [];
    render(
        <WorkProviders client={fake.client}>
            <WorkContext.Provider value={{ ask: (text) => void asked.push(text) }}>
                <InstructionsUnderName agent={agent} name={agent.name} role="Knows the Wirefern code and its customers" kept={agent.raw.noclick === true} />
            </WorkContext.Provider>
        </WorkProviders>
    );
    return { fake, asked };
}

const saves = (fake: ReturnType<typeof fakeWork>) => fake.requests.filter((r) => r.method === 'PATCH' && r.path === `/v1/agents/${id(1)}`);

it('shows their first lines under its name, opens them whole, and hands an ask to NoClick', async () => {
    const { asked } = await profile();
    const block = screen.getByTestId('agent-instructions');
    expect(block.textContent).toContain('Knows the Wirefern code and its customers.');
    // The line under its name is their first sentence: it isn't said twice.
    expect(within(block).queryAllByText('Knows the Wirefern code and its customers')).toHaveLength(0);
    fireEvent.click(within(block).getByRole('button', { name: 'Ask NoClick' }));
    expect(asked).toEqual(['Improve Wirefern’s instructions: ']);
    fireEvent.click(within(block).getByRole('button', { name: 'Show all' }));
    const sheet = await screen.findByTestId('instructions-sheet');
    await waitFor(() => expect(within(sheet).getByTestId('instructions-read').textContent).toContain('within two hours'));
    // Who changed them last, and each version with who made it, when and what it changed.
    expect(sheet.textContent).toContain('words, changed 2h ago by you.');
    const history = within(sheet).getByTestId('instructions-history');
    expect(history.textContent).toContain('You · 2h ago · 1 line changed');
    expect(history.textContent).toContain('NoClick, on your word');
    expect(history.textContent).toContain(`“${SAID}”`);
    expect(history.textContent).toContain('In use');
});

it('opens a version to what it changed', async () => {
    await profile();
    fireEvent.click(within(screen.getByTestId('agent-instructions')).getByRole('button', { name: 'Show all' }));
    const history = await screen.findByTestId('instructions-history');
    const noclicks = await within(history).findByRole('button', { name: /Version 2/ });
    fireEvent.click(noclicks);
    const diff = await within(history).findByTestId('diff');
    expect([...diff.querySelectorAll('tr[data-line="add"]')].map((row) => row.textContent)).toEqual(
        expect.arrayContaining([expect.stringContaining('Check the dead-letter queue first'), expect.stringContaining('Then read the failed request in the logs.')])
    );
    expect(diff.querySelectorAll('tr[data-line="del"]')).toHaveLength(1);
});

it('saves an edit on the text it started from', async () => {
    const { fake } = await profile();
    fireEvent.click(within(screen.getByTestId('agent-instructions')).getByRole('button', { name: 'Edit' }));
    const sheet = await screen.findByTestId('instructions-sheet');
    const box = await waitFor(() => {
        const field = within(sheet).getByRole('textbox') as HTMLTextAreaElement;
        expect(field.disabled).toBe(false);
        return field;
    });
    fireEvent.change(box, { target: { value: `${IN_USE}\n\nSign off as Wirefern.` } });
    fireEvent.click(within(sheet).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(within(sheet).queryByTestId('instructions-edit')).toBeNull());
    expect(saves(fake).map((r) => r.body)).toEqual([{ instructions: `${IN_USE}\n\nSign off as Wirefern.`, if_instructions: await digestOf(IN_USE) }]);
    await waitFor(() => expect(within(sheet).getByTestId('instructions-history').textContent).toMatch(/Version 4\s*You/));
});

it('shows a change NoClick made while you edit beside yours, and saves nothing until you choose', async () => {
    const { fake } = await profile({ instructionsRaced: true });
    fireEvent.click(within(screen.getByTestId('agent-instructions')).getByRole('button', { name: 'Edit' }));
    const sheet = await screen.findByTestId('instructions-sheet');
    const box = await waitFor(() => {
        const field = within(sheet).getByRole('textbox') as HTMLTextAreaElement;
        expect(field.disabled).toBe(false);
        return field;
    });
    const mine = IN_USE.replace('within two hours', 'within the day');
    fireEvent.change(box, { target: { value: mine } });
    fireEvent.click(within(sheet).getByRole('button', { name: 'Save' }));

    // Refused: theirs is in use and shown, with what NoClick was told; yours stays in the box.
    const changed = await within(sheet).findByTestId('instructions-changed');
    expect(changed.textContent).toContain('NoClick changed them just now, while you were editing.');
    expect(changed.textContent).toContain(RACED_SAID);
    expect((within(sheet).getByRole('textbox') as HTMLTextAreaElement).value).toBe(mine);
    expect((within(sheet).getByRole('button', { name: 'Save' }) as HTMLButtonElement).disabled).toBe(true);
    expect(fake.agents[0].instructions).toBe(RACED);

    // Keeping yours replaces theirs knowingly: the save names theirs as what it was made on.
    fireEvent.click(within(changed).getByRole('button', { name: 'Keep mine, replacing theirs' }));
    fireEvent.click(within(sheet).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(fake.agents[0].instructions).toBe(mine));
    expect(saves(fake).at(-1)?.body).toEqual({ instructions: mine, if_instructions: await digestOf(RACED) });
});

it('shows NoClick’s own agent with no editor', async () => {
    await profile({}, id(6));
    expect(screen.queryByTestId('agent-instructions')).toBeNull();
    expect(screen.getByText(/NoClick writes its instructions/)).toBeTruthy();
});
