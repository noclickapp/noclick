// The SINGLE mapping from an agent OAuth credential type to its sign-in component.
// Both surfaces that connect an agent CLI subscription render through here:
//   - the authenticated agent credential form (default socket transport)
//   - the public credential-provide page (an injected HTTP transport)
// Keeping the mapping in one place is the structural guarantee that the two can't
// diverge — a new OAuth provider is wired in exactly one spot and appears on both.

import { type ComponentType } from 'react';
import { CodexDeviceCodeAuth } from './CodexDeviceCodeAuth';
import { ClaudeCodeOAuth } from './ClaudeCodeOAuth';
import { GithubCopilotOAuth } from './GithubCopilotOAuth';
import { XaiOAuth } from './XaiOAuth';

// The common contract every agent OAuth sign-in component honours. `sendEvent` is
// the transport override — omitted → socket (agent form); provided → HTTP shim
// (provide page). Shared here so the shape can't drift between components.
export interface AgentOAuthComponentProps {
    credentialIds: Record<string, string>;
    onCredentialIdsChange: (credentialIds: Record<string, string>) => void;
    onCredentialCreated: () => Promise<void>;
    sendEvent?: (event: any) => Promise<any>;
}

// credential_type → component. The ONLY place this correspondence is declared.
const AGENT_OAUTH_COMPONENTS: Record<string, ComponentType<AgentOAuthComponentProps>> = {
    agent_codex_oauth: CodexDeviceCodeAuth,
    agent_claude_code_oauth: ClaudeCodeOAuth,
    agent_github_copilot_oauth: GithubCopilotOAuth,
    agent_xai_oauth: XaiOAuth,
};

/** Whether a credential type has an agent OAuth sign-in component. */
export function hasAgentOAuthConnect(credentialType: string): boolean {
    return credentialType in AGENT_OAUTH_COMPONENTS;
}

interface AgentOAuthConnectProps extends AgentOAuthComponentProps {
    credentialType: string;
}

export function AgentOAuthConnect({ credentialType, ...rest }: AgentOAuthConnectProps) {
    const Component = AGENT_OAUTH_COMPONENTS[credentialType];
    return Component ? <Component {...rest} /> : null;
}
