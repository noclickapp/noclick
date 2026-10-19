// The SINGLE mapping from an agent OAuth credential type to its sign-in component.
// Both surfaces that connect an agent CLI subscription render through here:
//   - the authenticated agent credential form (default socket transport)
//   - the public credential-provide page (an injected HTTP transport)
// Keeping the mapping in one place is the structural guarantee that the two can't
// diverge — a new OAuth provider is wired in exactly one spot and appears on both.
// Sign-ins a platform has its own agreements for register their component
// (agentOAuthRegistry, from the hosted frontend bootstrap); the backend
// reports which flows the instance offers, so an unregistered type is never asked for.

import type { ComponentType } from 'react';
import { CodexDeviceCodeAuth } from './CodexDeviceCodeAuth';
import { ClaudeCodeOAuth } from './ClaudeCodeOAuth';
import { platformAgentOAuthComponent, type AgentOAuthComponentProps } from './agentOAuthRegistry';

export { registerAgentOAuthComponent, type AgentOAuthComponentProps } from './agentOAuthRegistry';

// credential_type → component. The ONLY place this correspondence is declared.
const AGENT_OAUTH_COMPONENTS: Record<string, ComponentType<AgentOAuthComponentProps>> = {
    agent_codex_oauth: CodexDeviceCodeAuth,
    agent_claude_code_oauth: ClaudeCodeOAuth,
};

function componentFor(credentialType: string): ComponentType<AgentOAuthComponentProps> | undefined {
    return platformAgentOAuthComponent(credentialType) ?? AGENT_OAUTH_COMPONENTS[credentialType];
}

/** Whether a credential type has an agent OAuth sign-in component. */
export function hasAgentOAuthConnect(credentialType: string): boolean {
    return !!componentFor(credentialType);
}

interface AgentOAuthConnectProps extends AgentOAuthComponentProps {
    credentialType: string;
}

export function AgentOAuthConnect({ credentialType, ...rest }: AgentOAuthConnectProps) {
    const Component = componentFor(credentialType);
    return Component ? <Component {...rest} /> : null;
}
