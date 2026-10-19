import { describe, expect, it } from 'vitest';
import { companyAccountRow, describeAccount } from '~/components/shell/connections/accountNames';
import type { CredentialInfo } from '~/types/socket-events.generated';

const credential = (over: Partial<CredentialInfo>): CredentialInfo => ({
    id: 'c1',
    name: 'x',
    credential_type: 'x',
    created_at: '2026-06-15T12:00:00Z',
    updated_at: '2026-06-15T12:00:00Z',
    ...over,
});

describe('describeAccount', () => {
    it('leads with the catalog app and tells accounts apart by email', () => {
        const gmail = credential({ credential_type: 'google_gmail_oauth', name: 'ada@example.com', metadata: { email: 'ada@example.com' } });
        expect(describeAccount(gmail, 'Gmail')).toEqual({ app: 'Gmail', line: 'ada@example.com' });
    });

    it("prefers the account's handle to its email, but not GitHub's placeholder", () => {
        const github = credential({ credential_type: 'github_oauth', name: 'Work', metadata: { login: 'adalovelace', email: 'ada@example.com' } });
        expect(describeAccount(github, 'GitHub').line).toBe('adalovelace');
        const blind = credential({ credential_type: 'github_oauth', name: 'Work', metadata: { login: 'unknown', email: 'ada@example.com' } });
        expect(describeAccount(blind, 'GitHub').line).toBe('ada@example.com');
    });

    it('names an agent account by its company, and a sign-in by its plan', () => {
        const claude = credential({ credential_type: 'agent_claude_code_oauth', name: 'Anthropic (Claude Code)', metadata: { provider: 'claude_code' } });
        expect(describeAccount(claude)).toEqual({ app: 'Anthropic', line: 'Claude subscription' });
        expect(describeAccount(credential({ credential_type: 'agent_codex_oauth', name: 'ChatGPT (Codex)' }))).toEqual({ app: 'OpenAI', line: 'ChatGPT subscription' });
        // A harness's key is its company's: Claude Code runs on an Anthropic key, OpenClaw on an OpenRouter one.
        expect(describeAccount(credential({ credential_type: 'agent_claude_code', name: 'Mine' })).app).toBe('Anthropic');
        expect(describeAccount(credential({ credential_type: 'agent_openclaw', name: 'Mine' })).app).toBe('OpenRouter');
        // The provider's own casing, not a title-cased slug.
        expect(describeAccount(credential({ credential_type: 'agent_deepseek', name: 'Mine' })).app).toBe('DeepSeek');
        expect(describeAccount(credential({ credential_type: 'agent_opencode', name: 'Mine' })).app).toBe('OpenCode');
    });

    it("replaces the connect form's own name with when the account was added", () => {
        const dated = credential({ credential_type: 'apollo_api_key', name: 'ApolloAPIKey - 6/15/2026' });
        expect(describeAccount(dated, 'Apollo').line).toBe('Added Jun 15, 2026');
        const bare = credential({ credential_type: 'notion_integration_token', name: 'notion_integration_token' });
        expect(describeAccount(bare, 'Notion').line).toBe('Added Jun 15, 2026');
        const router = credential({ credential_type: 'agent_openrouter', name: 'OpenRouter - 6/10/2026', created_at: '2026-06-10T12:00:00Z' });
        expect(describeAccount(router)).toEqual({ app: 'OpenRouter', line: 'Added Jun 10, 2026' });
    });

    it('keeps a name someone chose', () => {
        expect(describeAccount(credential({ credential_type: 'linear_pat', name: 'Work' }), 'Linear').line).toBe('Work');
    });

    it('shows an env bundle by its variables', () => {
        const env = credential({ credential_type: 'agent_env', name: 'Agent env vars - 7/22/2026', metadata: { var_names: ['API_KEY', 'DB_URL', 'REGION', 'TOKEN'] } });
        expect(describeAccount(env)).toEqual({ app: 'Environment variables', line: 'API_KEY, DB_URL, REGION +1' });
        expect(describeAccount(credential({ credential_type: 'agent_env', metadata: { var_names: [] } })).line).toBe('No variables yet');
    });

    it('names an MCP server by its provider and host', () => {
        const mcp = credential({ credential_type: 'mcp_oauth', name: 'Notion (mcp.notion.com)', metadata: { provider_name: 'Notion', server_url: 'https://mcp.notion.com/mcp' } });
        expect(describeAccount(mcp)).toEqual({ app: 'Notion', line: 'MCP server · mcp.notion.com' });
    });
});

describe('companyAccountRow', () => {
    const row = (over: Partial<CredentialInfo>) => {
        const c = credential(over);
        return companyAccountRow(c, describeAccount(c).line);
    };

    it('titles a sign-in by its plan, or by the account it signed in as', () => {
        expect(row({ credential_type: 'agent_claude_code_oauth', name: 'Anthropic (Claude Code)' })).toEqual({ title: 'Claude subscription', meta: 'Added Jun 15, 2026' });
        expect(row({ credential_type: 'agent_codex_oauth', name: 'ChatGPT (Codex)', metadata: { email: 'ada@example.com' } })).toEqual({ title: 'ada@example.com', meta: 'ChatGPT subscription' });
    });

    it('titles a key by the name you gave it, and a default-named one as "API key"', () => {
        expect(row({ credential_type: 'agent_anthropic', name: 'Work' })).toEqual({ title: 'Work', meta: 'API key' });
        expect(row({ credential_type: 'agent_anthropic', name: 'Anthropic - 6/15/2026' })).toEqual({ title: 'API key', meta: 'Added Jun 15, 2026' });
    });
});
