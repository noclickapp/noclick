import { describe, expect, it } from 'vitest';
import { acceptedAgentCredentialTypes, agentCompanies, sameAccountAgentProviders } from '~/lib/agentCredentialModel';
import { ModelProvider } from '~/types/provider';

const company = (id: string) => agentCompanies().find((c) => c.id === id);

describe('agentCompanies', () => {
    it('folds a CLI harness into the company whose key and sign-in it takes', () => {
        expect(company('anthropic')).toEqual({ id: 'anthropic', title: 'Anthropic', members: [ModelProvider.ANTHROPIC, ModelProvider.CLAUDE_CODE] });
        expect(company('openai')).toEqual({ id: 'openai', title: 'OpenAI', members: [ModelProvider.OPENAI, ModelProvider.CODEX] });
        expect(company('openrouter')?.members).toEqual([ModelProvider.OPENROUTER, ModelProvider.OPENCLAW, ModelProvider.HERMES_AGENT]);
    });

    it('keeps an account of its own apart', () => {
        expect(company('opencode')?.members).toEqual([ModelProvider.OPENCODE]);
        expect(company('xai')?.members).toEqual([ModelProvider.XAI]);
    });

    it('shows a product family as one company, named apart from the app it sits beside', () => {
        expect(company('github')).toEqual({ id: 'github', title: 'GitHub Copilot', members: [ModelProvider.GITHUB_COPILOT, ModelProvider.GITHUB_MODELS] });
    });

    it('lists every provider once, and no harness as a company of its own', () => {
        const members = agentCompanies().flatMap((c) => c.members);
        expect(new Set(members).size).toBe(members.length);
        const titles = agentCompanies().map((c) => c.title);
        for (const harness of ['Claude Code', 'OpenAI Codex', 'OpenClaw', 'Hermes Agent']) expect(titles).not.toContain(harness);
    });
});

describe('acceptedAgentCredentialTypes', () => {
    it("accepts the key of every provider sharing the account: one Anthropic key runs Claude Code and Anthropic models", () => {
        expect(acceptedAgentCredentialTypes(ModelProvider.CLAUDE_CODE)).toEqual(['agent_claude_code', 'agent_anthropic', 'agent_claude_code_oauth']);
        expect(acceptedAgentCredentialTypes(ModelProvider.CODEX)).toEqual(['agent_codex', 'agent_openai', 'agent_codex_oauth']);
    });

    it('takes a Claude plan only for Claude Code', () => {
        expect(acceptedAgentCredentialTypes(ModelProvider.ANTHROPIC)).toEqual(['agent_anthropic', 'agent_claude_code']);
    });

    it('never across a product family: a GitHub Models token is not a Copilot sign-in', () => {
        expect(sameAccountAgentProviders(ModelProvider.GITHUB_MODELS)).toEqual([]);
        expect(acceptedAgentCredentialTypes(ModelProvider.GITHUB_COPILOT)).not.toContain('agent_github_models');
    });
});
