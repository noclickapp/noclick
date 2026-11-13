// How an account reads on a tile: the app it belongs to, and one line that
// tells two accounts of the same app apart in words you'd recognise (the
// account's handle or email, an env bundle's variables, an MCP server's host),
// not the name the connect form filled in on its own.
import type { CredentialInfo } from '~/types/socket-events.generated';
import { formatCredentialTypeLabel } from '~/utils/credentialTypes';
import { AGENT_ENV_CREDENTIAL_TYPE, AGENT_SIGN_IN_NAMES, agentCompanies, subscriptionLine, type AgentCompany } from '~/lib/agentCredentialModel';
import type { ModelProvider } from '~/types/provider';

const text = (value: unknown): string | null => (typeof value === 'string' && value.trim() ? value.trim() : null);

function serverHost(credential: CredentialInfo): string | null {
    const url = text(credential.metadata?.server_url);
    if (!url) return null;
    try {
        return new URL(url).hostname;
    } catch {
        return null;
    }
}

/** The company an agent's key or sign-in is with, the way Connections lists AI accounts. */
function companyOf(type: string): AgentCompany | undefined {
    const provider = type.replace(/^agent_/, '').replace(/_oauth$/, '') as ModelProvider;
    return type.startsWith('agent_') ? agentCompanies().find((c) => c.members.includes(provider)) : undefined;
}

/** A key with no app of its own: "agent_claude_code_oauth" reads "Claude". */
function kindName(credential: CredentialInfo): string {
    const type = credential.credential_type;
    if (type === AGENT_ENV_CREDENTIAL_TYPE) return 'Environment variables';
    if (type.startsWith('mcp_')) return text(credential.metadata?.provider_name) ?? serverHost(credential) ?? 'MCP server';
    return companyOf(type)?.title ?? formatCredentialTypeLabel(type.replace(/^agent_/, '').replace(/_(oauth|api_key|key|token|pat)$/, ''));
}

/** The name the connect form fills in when you don't pick one: the key's class and the date, or the type itself. */
function isDefaultName(credential: CredentialInfo): boolean {
    const name = credential.name.trim();
    const type = credential.credential_type;
    return /^.+ - \d{1,2}\/\d{1,2}\/\d{4}$/.test(name) || name.toLowerCase() === type || name.toLowerCase() === formatCredentialTypeLabel(type).toLowerCase();
}

export function addedLabel(iso: string): string {
    return `Added ${new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}`;
}

function accountLine(credential: CredentialInfo, app: string): string {
    const meta = credential.metadata ?? {};
    // A handle (GitHub's login) before an email: it's the name the account goes by. GitHub's OAuth writes
    // "unknown" when the profile call fails.
    const login = text(meta.login);
    const identity = (login !== 'unknown' ? login : null) ?? text(meta.email);
    if (identity) return identity;
    // A subscription sign-in is named by its plan, not the name its handler gave it ("Claude (Claude Code)").
    if (AGENT_SIGN_IN_NAMES[credential.credential_type]) return subscriptionLine([credential.credential_type], app);
    if (credential.credential_type === AGENT_ENV_CREDENTIAL_TYPE && Array.isArray(meta.var_names)) {
        const names = meta.var_names.filter((n): n is string => typeof n === 'string');
        if (!names.length) return 'No variables yet';
        return names.length > 3 ? `${names.slice(0, 3).join(', ')} +${names.length - 3}` : names.join(', ');
    }
    if (credential.credential_type.startsWith('mcp_')) return ['MCP server', serverHost(credential)].filter(Boolean).join(' · ');
    // An app connected through its own MCP server: who signed in, when the sign-in said.
    if (text(meta.mcp_server_url)) return ['Through MCP', text(meta.verified_as)].filter(Boolean).join(' · ');
    if (isDefaultName(credential) || credential.name.trim() === app) return addedLabel(credential.created_at);
    return credential.name;
}

/** `app` is the catalog app's name when the account belongs to one. */
export function describeAccount(credential: CredentialInfo, app?: string): { app: string; line: string } {
    const name = app ?? kindName(credential);
    return { app: name, line: accountLine(credential, name) };
}

/** The other names search finds an account's app by: an AI account's company's ("Anthropic" for Claude). */
export const accountAliases = (credential: CredentialInfo): string[] => companyOf(credential.credential_type)?.aliases ?? [];

/** An AI account in its company's list, where the company goes without saying: what it is (the email, login or
 *  name it carries, else its plan or "API key") over what kind it is or when it was added. */
export function companyAccountRow(credential: CredentialInfo, line: string): { title: string; meta: string } {
    const type = credential.credential_type;
    const kind = AGENT_SIGN_IN_NAMES[type] ? subscriptionLine([type], companyOf(type)?.title ?? '') : 'API key';
    const added = addedLabel(credential.created_at);
    return line !== added && line !== kind ? { title: line, meta: kind } : { title: kind, meta: added };
}
