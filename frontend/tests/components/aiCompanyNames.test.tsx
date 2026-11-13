// @vitest-environment happy-dom
// Anthropic and OpenAI as people know them: Claude and ChatGPT wherever an AI account's company shows, Claude wearing
// its spark on its API key as on its plan, and each found by either name wherever a person searches.
import { cleanup, render, screen } from '@testing-library/react';
import { SiClaude } from 'react-icons/si';
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('~/hooks/useConnectionProbe', () => ({ lastConnectionProbe: () => undefined }));

import { ConnectedList } from '~/components/shell/connections/ConnectedList';
import { accountAliases, describeAccount } from '~/components/shell/connections/accountNames';
import type { ConnectedAccount } from '~/components/shell/connections/accounts';
import { AiMark, agentMark, aiCompanies, companySearchFields } from '~/components/shell/connections/aiAccounts';
import { scoreFields } from '~/lib/fuzzyRank';
import { normalizeForSearch } from '~/lib/modelFiltering';
import { ModelProvider, providerSearchTerms } from '~/types/provider';
import type { CredentialInfo } from '~/types/socket-events.generated';
import { getCredentialIcon } from '~/utils/credentialIcons';

afterEach(cleanup);

const CLAUDE_ORANGE = '#D97757';
const SIGN_INS = { claude_code: 'agent_claude_code_oauth', codex: 'agent_codex_oauth' };

const credential = (credential_type: string, name: string): CredentialInfo =>
    ({ id: credential_type, name, credential_type, access_type: 'owner', created_at: '2026-11-14T12:00:00Z', updated_at: '2026-11-14T12:00:00Z' }) as CredentialInfo;

/** An account as Connections builds it (useConnectedAccounts). */
const account = (credential_type: string, name: string): ConnectedAccount => {
    const c = credential(credential_type, name);
    return { credential: c, ...describeAccount(c), aliases: accountAliases(c), source: 'connected' };
};

const ACCOUNTS = [
    account('agent_anthropic', 'Anthropic - 11/14/2026'),
    account('agent_claude_code_oauth', 'Anthropic (Claude Code)'),
    account('agent_openai', 'OpenAI - 11/14/2026'),
    account('agent_codex_oauth', 'ChatGPT (Codex)'),
    { ...account('google_gmail_oauth', 'ada@example.com'), app: 'Gmail', line: 'ada@example.com' },
];

/** The path of the spark Claude's plan wears, as react-icons draws it. */
function sparkPath(): string | null {
    const { container, unmount } = render(<SiClaude />);
    const d = container.querySelector('path')?.getAttribute('d') ?? null;
    unmount();
    expect(d).toBeTruthy();
    return d;
}

describe('the AI companies, as people know them', () => {
    const companies = aiCompanies(SIGN_INS);
    const company = (id: string) => companies.find((c) => c.id === id)!;

    it('are Claude and ChatGPT, each tile saying it signs in with a subscription without repeating its name', () => {
        expect(company('anthropic')).toMatchObject({ title: 'Claude', aliases: ['Anthropic'], line: 'Subscription', uses: 'Claude models and Claude Code for your agents.' });
        expect(company('openai')).toMatchObject({ title: 'ChatGPT', aliases: ['OpenAI'], line: 'Subscription' });
    });

    it('answer search by either name, in Connections and in the model pickers', () => {
        const found = (q: string) => companies.filter((c) => scoreFields(q, companySearchFields(c)) !== null).map((c) => c.title);
        for (const q of ['claude', 'anthropic', 'Claude', 'Anthropic']) expect(found(q)).toContain('Claude');
        for (const q of ['chatgpt', 'openai', 'ChatGPT', 'OpenAI']) expect(found(q)).toContain('ChatGPT');
        expect(found('anthropic')).not.toContain('ChatGPT');
        expect(found('openai')).not.toContain('Claude');

        // The pickers' provider rail (ModelPickerModal, ModelDropdown) reads the same names.
        const rail = (q: string) =>
            [ModelProvider.ANTHROPIC, ModelProvider.OPENAI, ModelProvider.GEMINI].filter((p) => providerSearchTerms(p).some((t) => normalizeForSearch(t).includes(normalizeForSearch(q))));
        expect(rail('claude')).toEqual([ModelProvider.ANTHROPIC]);
        expect(rail('anthropic')).toEqual([ModelProvider.ANTHROPIC]);
        expect(rail('chatgpt')).toEqual([ModelProvider.OPENAI]);
        expect(rail('openai')).toEqual([ModelProvider.OPENAI]);
    });
});

describe('their marks', () => {
    it("put Claude's spark on its API key, in Claude's orange, as on its plan", () => {
        const plan = getCredentialIcon('agent_claude_code_oauth');
        expect(getCredentialIcon('agent_anthropic')).toMatchObject({ Icon: plan.Icon, iconColor: CLAUDE_ORANGE });
        expect(agentMark('agent_anthropic')).toEqual({ Icon: plan.Icon, iconColor: CLAUDE_ORANGE });
    });

    it("keep ChatGPT's own mark, the same on its key as on its plan", () => {
        expect(getCredentialIcon('agent_openai').Icon).toBe(getCredentialIcon('agent_codex_oauth').Icon);
    });

    it("draw Claude's tile with the spark", () => {
        const { container } = render(<AiMark provider={ModelProvider.ANTHROPIC} />);
        const svg = container.querySelector('svg')!;
        expect(svg.querySelector('path')?.getAttribute('d')).toBe(sparkPath());
        expect(svg.getAttribute('style')).toContain('color: #D97757');
    });
});

describe('the accounts list', () => {
    const tiles = (query: string) => {
        cleanup();
        render(<ConnectedList accounts={ACCOUNTS} source="connected" query={query} loaded onOpen={() => undefined} onBrowse={() => undefined} />);
        return screen.queryAllByTestId('connected-account').map((tile) => tile.textContent);
    };

    it('names each account by its company, a plan as just its subscription, the API key with the spark too', () => {
        render(<ConnectedList accounts={ACCOUNTS} source="connected" query="" loaded onOpen={() => undefined} onBrowse={() => undefined} />);
        const shown = screen.getAllByTestId('connected-account');
        const text = shown.map((tile) => tile.textContent);
        expect(text).toEqual(expect.arrayContaining([expect.stringMatching(/^ClaudeAdded Nov 14, 2026/), expect.stringMatching(/^ClaudeSubscription/), expect.stringMatching(/^ChatGPTSubscription/)]));
        expect(text.join(' ')).not.toMatch(/Anthropic|OpenAI|Claude subscription|ChatGPT subscription/);
        const spark = sparkPath();
        const claudeTiles = shown.filter((tile) => tile.textContent?.startsWith('Claude'));
        expect(claudeTiles).toHaveLength(2);
        for (const tile of claudeTiles) expect(tile.querySelector('svg path')?.getAttribute('d')).toBe(spark);
    });

    it('finds Claude by "claude" or "anthropic", and ChatGPT by "chatgpt" or "openai"', () => {
        for (const q of ['claude', 'anthropic']) {
            const found = tiles(q);
            expect(found).toHaveLength(2);
            for (const t of found) expect(t).toMatch(/^Claude/);
        }
        for (const q of ['chatgpt', 'openai']) {
            const found = tiles(q);
            expect(found).toHaveLength(2);
            for (const t of found) expect(t).toMatch(/^ChatGPT/);
        }
    });
});
