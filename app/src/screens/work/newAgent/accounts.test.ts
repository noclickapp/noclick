// The account an agent moving onto another harness takes (switchAccount): the one it runs on while that still runs the
// pick, the one of yours that does with no question, a choice where several do, NoClick's key where none of yours does
// and the key runs it, else a connect; NoClick's own runtime always takes NoClick's key.
import { describe, expect, it } from 'vitest';
import { Connection, type HarnessInfo, type HarnessInfo as Harness, type HarnessName } from 'noclick';
import { accountRefusal, accountsOf, firstUsable, menuTitle, NOCLICK_KEY_ACCOUNT, switchAccount, switchChoices, type ModelAccount } from './accounts';

const harness = (name: HarnessName, noclickKey = false): HarnessInfo =>
    ({ name, defaultModel: `${name}-model`, integrations: ['anthropic', 'openai', 'openrouter'], noclickKey: { runs: noclickKey, models: [], why: null } }) as unknown as HarnessInfo;
const account = (id: string, kind: ModelAccount['kind'], integration: string, connected = true): ModelAccount => ({
    id, kind, integration, providerLabel: null, name: null, note: '', connected, status: connected ? 'connected' : 'disconnected',
});

const PLAN = account('plan', 'claude_plan', 'anthropic');
const KEY = account('claude-key', 'anthropic_key', 'anthropic');
const CHATGPT = account('chatgpt', 'chatgpt_plan', 'openai');

describe('the account a harness move takes', () => {
    it('takes the one of yours that runs it, with no question', () => {
        expect(switchAccount([PLAN, CHATGPT], harness('claude_code'), 'claude-sonnet-5-5', null)).toEqual({ account: PLAN });
    });

    it('offers a choice where several of yours run it, unless it runs on one already', () => {
        expect(switchAccount([PLAN, KEY, CHATGPT], harness('claude_code'), 'claude-sonnet-5-5', null)).toEqual({ choose: [PLAN, KEY] });
        expect(switchAccount([PLAN, KEY], harness('claude_code'), 'claude-sonnet-5-5', 'claude-key')).toEqual({ account: KEY });
    });

    it('asks for a connect where none of yours runs it, a signed-out one included', () => {
        expect(switchAccount([CHATGPT, account('old', 'claude_plan', 'anthropic', false)], harness('claude_code'), 'claude-sonnet-5-5', null)).toEqual({ connect: true });
    });

    it('runs on NoClick’s key where none of yours runs it and the key does', () => {
        expect(switchAccount([PLAN], harness('codex', true), 'gpt-6-luna', null)).toEqual({ account: NOCLICK_KEY_ACCOUNT });
        expect(switchAccount([PLAN, CHATGPT], harness('codex', true), 'gpt-6-luna', null)).toEqual({ account: CHATGPT });
    });

    it('moves NoClick’s own runtime onto NoClick’s key', () => {
        expect(switchAccount([KEY], harness('sdk'), 'claude-sonnet-5-5', null)).toEqual({ account: NOCLICK_KEY_ACCOUNT });
    });
});

describe('a plan’s tier and usage', () => {
    const listed = (raw: Record<string, unknown>) =>
        (Connection as unknown as { _of: (init: { raw: Record<string, unknown> }) => Connection })._of({ raw: { object: 'connection', status: 'connected', origin: 'api', ...raw } });
    const TIGHTEST = { kind: 'five_hour', label: '5-hour', models: [], used: 0.9, left: 0.1, resets_at: null, state: 'near' };
    const connections = [
        listed({ id: 'conn-1', name: 'claude', integration: 'anthropic', credential_type: 'agent_claude_code_oauth', plan: { tier: 'max_20x', label: 'Ultra', runs: ['claude_code'], refusal: null }, usage: { state: 'near', tightest: TIGHTEST, available_at: null, as_of: null } }),
        listed({ id: 'conn-2', name: 'claude-free', integration: 'anthropic', credential_type: 'agent_claude_code_oauth', plan: { tier: 'free', label: 'Free', runs: [], refusal: 'Claude Free doesn’t include Claude Code.' }, usage: null }),
        listed({ id: 'conn-3', name: 'anthropic', integration: 'anthropic', credential_type: 'agent_anthropic', plan: null, usage: null }),
    ];
    const accounts = accountsOf(connections, new Set(['anthropic']));
    const claudeCode = harness('claude_code') as Harness;

    it('carries a plan’s tier, usage and connection id onto its account, and nothing onto a key', () => {
        expect(accounts[0]).toMatchObject({ connectionId: 'conn-1', plan: { label: 'Ultra' }, usage: { state: 'near', tightest: { label: '5-hour', left: 0.1 } } });
        expect(accounts[2]).not.toHaveProperty('plan');
        expect(accounts[2]).not.toHaveProperty('usage');
    });

    it('a tier that runs nothing says so and never runs the pick', () => {
        expect(accountRefusal(accounts[1], claudeCode, 'claude-opus-5-5', 'Opus 5.5')).toBe('Claude Free doesn’t include Claude Code.');
        expect(accountRefusal(accounts[0], claudeCode, 'claude-opus-5-5', 'Opus 5.5')).toBeNull();
        expect(firstUsable([accounts[1], accounts[2]], claudeCode, 'claude-opus-5-5')?.id).toBe('anthropic');
    });
});

describe('what an agent may move between when a plan runs out', () => {
    const own = account('claude', 'claude_plan', 'anthropic');
    const shared: ModelAccount = { ...account('team', 'claude_plan', 'anthropic'), access: 'edit' };
    const free: ModelAccount = { ...account('kid', 'claude_plan', 'anthropic'), plan: { tier: 'free', label: 'Free', runs: [], refusal: 'Claude Free doesn’t include Claude Code.', raw: {} } };
    const keys = [account('claude-key', 'anthropic_key', 'anthropic'), account('router', 'openrouter_key', 'openrouter'), account('other', 'key', 'mistral'), account('gone', 'openai_key', 'openai', false)];

    it('takes your own connected plans and keys that run a coding harness, never one shared with you or a tier that runs nothing', () => {
        expect(switchChoices([own, shared, free, ...keys], harness('claude_code')).map((a) => a.id)).toEqual(['claude', 'claude-key', 'router']);
    });

    it('adds NoClick’s key only where it runs the agent’s harness, and nothing on NoClick’s own runtime’s say-so', () => {
        expect(switchChoices([own], harness('codex', true)).at(-1)).toBe(NOCLICK_KEY_ACCOUNT);
        expect(switchChoices([own], harness('claude_code'))).toEqual([own]);
        expect(switchChoices([own], harness('sdk'))).toEqual([own]);
    });
});

describe('an account as the account menu names it', () => {
    it('names a plan by its email, its logo saying which plan, else by its kind and what tells it apart', () => {
        expect(menuTitle({ ...PLAN, email: 'rowan@example.com', name: 'rowan@example.com' })).toBe('rowan@example.com');
        expect(menuTitle({ ...CHATGPT, email: null, name: 'Added Sep 11, 2025' })).toBe('ChatGPT plan · Added Sep 11, 2025');
        expect(menuTitle({ ...CHATGPT, email: null })).toBe('ChatGPT plan');
    });

    // The open app names a key by its provider ("Anthropic key"); the hosted app fills in the company ("Claude key").
    it('names a key by its kind and its name, else who it is, and never how it stopped', () => {
        expect(menuTitle({ ...KEY, name: 'work' })).toBe('Anthropic key · work');
        expect(menuTitle({ ...KEY, email: 'Key ending 4f2a' })).toBe('Anthropic key · Key ending 4f2a');
        expect(menuTitle({ ...KEY, status: 'disconnected', down: { reason: 'refused', message: '' } })).toBe('Anthropic key');
        expect(menuTitle(NOCLICK_KEY_ACCOUNT)).toBe('NoClick’s key');
    });
});
