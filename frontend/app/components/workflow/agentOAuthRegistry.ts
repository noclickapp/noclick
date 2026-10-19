// Sign-ins a platform has its own agreements for (registerAgentOAuthComponent, from the hosted frontend bootstrap).
// Apart from AgentOAuthConnect, which carries the engine's own sign-in components, so registering one costs nothing
// on the pages that never sign in.
import type { ComponentType, ReactNode } from 'react';

// The common contract every agent OAuth sign-in component honours. `sendEvent` is
// the transport override — omitted → socket (agent form); provided → HTTP shim
// (provide page). Shared here so the shape can't drift between components.
export interface AgentOAuthComponentProps {
    credentialIds: Record<string, string>;
    onCredentialIdsChange: (credentialIds: Record<string, string>) => void;
    onCredentialCreated: () => Promise<void>;
    sendEvent?: (event: any) => Promise<any>;
    /** A host with its own call to action draws the idle state instead of the default button: given the flow's
     *  start and the sign-in's note (what it needs). The running flow renders as usual. */
    renderStart?: (start: () => void, note: ReactNode) => ReactNode;
}

const PLATFORM_COMPONENTS: Record<string, ComponentType<AgentOAuthComponentProps>> = {};

/** Add a platform's own sign-in component for a credential type. */
export function registerAgentOAuthComponent(
    credentialType: string,
    component: ComponentType<AgentOAuthComponentProps>
): void {
    PLATFORM_COMPONENTS[credentialType] = component;
}

export function platformAgentOAuthComponent(credentialType: string): ComponentType<AgentOAuthComponentProps> | undefined {
    return PLATFORM_COMPONENTS[credentialType];
}
