// @vitest-environment happy-dom
// The model picker in an agent's conversation, over the fake /v1 through the real SDK. A laptop opens it as a popover
// with the search ready to type in, the agents listed by name beside the open one's models. A phone opens it as a
// sheet over the page, the agents on a shelf, on its models: the search isn't focused, so no keyboard covers them. The
// model's effort is set on a slider, saved once it's let go; a model with no effort to set shows none. Fast is one
// switch in the foot.
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { PhoneBarSlotProvider } from '@/ui/phoneBar';
import { WorkProviders } from '../agents/fixtures/providers';
import { AgentConversation } from './AgentConversation';
import { AGENT_ID, fakeWorkAgent, settingsFor } from './fixtures/workAgent';

beforeEach(() => vi.stubGlobal('fetch', async () => new Response(null, { status: 404 })));
afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
});

async function openPicker({ phone = false, fake = fakeWorkAgent() }: { phone?: boolean; fake?: ReturnType<typeof fakeWorkAgent> } = {}) {
    const conversation = <AgentConversation agentId={AGENT_ID} conversation="main" onOpenProfile={() => undefined} onOpenMachine={() => undefined} />;
    render(
        <WorkProviders client={fake.client}>
            {phone ? (
                <PhoneBarSlotProvider slot={null} lead={null} setLeadTaken={() => undefined}>
                    {conversation}
                </PhoneBarSlotProvider>
            ) : (
                conversation
            )}
        </WorkProviders>
    );
    fireEvent.click(await screen.findByRole('button', { name: /^Model: / }));
    return { fake, models: await screen.findByRole('listbox', { name: 'Models' }) };
}

/** What the conversation's settings were sent, in order. */
const sent = (fake: ReturnType<typeof fakeWorkAgent>) => fake.requests.filter((r) => r.method === 'PATCH' && r.path.endsWith('/conversations/main')).map((r) => r.body);

it('opens as a sheet over the page on a phone, on its models and not in the search, the agents named on a shelf', async () => {
    const { models } = await openPicker({ phone: true });
    const sheet = screen.getByRole('dialog', { name: 'Model' });
    expect(sheet.contains(models)).toBe(true);
    // The sheet's layer covers the page; the laptop's popover is not what opened.
    expect(sheet.closest('.fixed.inset-0')).toBeTruthy();
    expect(models.closest('[data-radix-popper-content-wrapper]')).toBeNull();
    expect(document.activeElement).not.toBe(within(sheet).getByRole('textbox', { name: 'Search models' }));
    // Starred is its star alone there; each agent is its name.
    const shelf = within(sheet).getByLabelText('Harnesses');
    expect(Array.from(shelf.querySelectorAll('button')).map((b) => [b.getAttribute('aria-label'), b.textContent])).toEqual([
        ['Starred', ''],
        ['Claude Code', 'Claude Code'],
        ['Codex', 'Codex'],
        ['NoClick agent', 'NoClick agent'],
    ]);
});

it('opens as a popover on a laptop, ready to search, the agents listed by name and each model starred from its row', async () => {
    const { models } = await openPicker();
    expect(screen.queryByRole('dialog', { name: 'Model' })).toBeNull();
    expect(models.closest('[data-radix-popper-content-wrapper]')).toBeTruthy();
    expect(document.activeElement).toBe(screen.getByRole('textbox', { name: 'Search models' }));
    expect(Array.from(screen.getByLabelText('Harnesses').querySelectorAll('button')).map((b) => b.textContent)).toEqual(['Starred', 'Claude Code', 'Codex', 'NoClick agent']);

    const star = within(models).getByRole('button', { name: 'Star Sonnet 5.5' });
    fireEvent.click(star);
    expect(within(models).getByRole('button', { name: 'Remove Sonnet 5.5 from starred' }).getAttribute('aria-pressed')).toBe('true');
    fireEvent.click(screen.getByRole('button', { name: 'Starred' }));
    await waitFor(() => expect(within(screen.getByRole('listbox', { name: 'Models' })).getAllByRole('option')).toHaveLength(1));
});

it('sets the model’s effort on a slider, saved a moment after the last key', async () => {
    const { fake } = await openPicker();
    const slider = screen.getByRole('slider', { name: 'Effort' });
    expect([slider.getAttribute('aria-valuetext'), screen.getByTestId('effort-level').textContent]).toEqual(['High', 'High']);
    expect(screen.getByTestId('effort').dataset.open).toBe('true');

    fireEvent.keyDown(slider, { key: 'ArrowLeft' });
    fireEvent.keyDown(slider, { key: 'ArrowLeft' });
    expect(slider.getAttribute('aria-valuetext')).toBe('Low');
    expect(sent(fake)).toEqual([]);
    await waitFor(() => expect(sent(fake)).toEqual([{ effort: 'low' }]));
    await waitFor(() => expect(screen.getByRole('button', { name: /^Model: / }).getAttribute('aria-label')).toBe('Model: Opus 5.5, low'));
    expect(slider.getAttribute('aria-valuetext')).toBe('Low');
    // Let go where it already was, nothing is sent again.
    fireEvent.keyDown(slider, { key: 'Home' });
    await act(() => new Promise((r) => setTimeout(r, 600)));
    expect(sent(fake)).toHaveLength(1);
});

it('shows no effort for a model with none to set', async () => {
    await openPicker({ fake: fakeWorkAgent({ settings: { main: settingsFor('main', { efforts: [], effort: null }) } }) });
    expect(screen.getByTestId('effort').dataset.open).toBe('false');
    expect(screen.queryByRole('slider')).toBeNull();
});

it('turns Fast on and off from the foot', async () => {
    const { fake } = await openPicker();
    const fast = screen.getByRole('button', { name: 'Fast' });
    expect(fast.getAttribute('aria-pressed')).toBe('false');
    fireEvent.click(fast);
    await waitFor(() => expect(sent(fake)).toEqual([{ speed: 'fast' }]));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Fast' }).getAttribute('aria-pressed')).toBe('true'));
    fireEvent.click(screen.getByRole('button', { name: 'Fast' }));
    await waitFor(() => expect(sent(fake)).toEqual([{ speed: 'fast' }, { speed: 'standard' }]));
});

it('names a model its harness lists by an alias as the list does, in the box and in the list', async () => {
    // Claude Code's list as the API answers it: aliases, each naming the model it runs. The agent holds the model's
    // own id (set through the API), which no row's id is.
    const claudeCode = [
        { id: 'sonnet', label: 'Claude Sonnet 5.5 (latest)', canonical: 'claude-sonnet-5-5' },
        { id: 'opus', label: 'Claude Opus 5.5 (latest)', canonical: 'claude-opus-5-5' },
    ];
    const fake = fakeWorkAgent({ agent: { harness: 'claude_code', model: 'claude-opus-5-5' }, models: { claude_code: claudeCode } });
    const { models } = await openPicker({ fake });
    const chip = screen.getByRole('button', { name: /^Model: / });
    await waitFor(() => expect(chip.textContent).toContain('Claude Opus 5.5'));
    expect(chip.textContent).not.toContain('claude-opus-5-5');
    const current = within(models).getByRole('option', { selected: true });
    expect(current.textContent).toContain('Claude Opus 5.5');
});

it('reads a model its harness has never named, or names by its id alone, as its name', async () => {
    const { idName, modelName } = await import('../newAgent/catalog');
    // Codex's list labels each model with its id.
    expect(modelName('gpt-5.6-luna', 'gpt-5.6-luna')).toBe('GPT-5.6 Luna');
    expect(modelName('gpt-5-codex (ChatGPT API key only)', 'gpt-5-codex')).toBe('GPT-5 Codex (ChatGPT API key only)');
    expect(modelName('[OpenRouter] OpenAI: GPT-6 Luna', 'openrouter/openai/gpt-6-luna')).toBe('GPT-6 Luna');
    expect(idName('claude-opus-5-5')).toBe('Claude Opus 5.5');
    expect(idName('anthropic/claude-sonnet-4-5-20250929')).toBe('Claude Sonnet 4.5');
    expect(idName('gpt-5.5')).toBe('GPT-5.5');
    expect(idName('openrouter/~openai/gpt-luna-latest')).toBe('GPT Luna Latest');
});
