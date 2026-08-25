import { useCallback, useEffect, useRef } from 'react';
import { Node } from '@xyflow/react';
import type { CredentialVariable } from '~/hooks/useCredentialVariables';
import type { CredentialDisplayMeta } from '~/utils/credentialAutoSelect';
import {
    BANNER_PULSE_CYCLES,
    claimPulse,
    credentialsPulseKey,
    onPulseRequested,
    pulseElement,
} from '~/lib/pulseHighlight';
import { NodeCredentials } from '../NodeCredentials';
import { TabEmptyState } from './TabEmptyState';

interface CredentialsTabContentProps {
    selectedNode: Node | null;
    /** Nested config fields extracted from selectedNode.data.config. */
    nodeConfig: Record<string, any>;
    /** Raw credential IDs (with {{vars.*}} references intact, for display). */
    rawCredentialIds: Record<string, string>;
    credentialVariables?: CredentialVariable[];
    onCredentialChange: (newCredentialIds: Record<string, string>, credentialMeta?: Record<string, CredentialDisplayMeta>, credentialRemoved?: string[]) => void;
}

/**
 * Flashes the pulse ring around the credential controls, but only when someone
 * has been sent here to use them — today, the Run popup's "Connect" button.
 *
 * Deliberately NOT "pulse whenever this node still needs an account": that
 * fires on every ordinary visit to the tab, including the ones where the user
 * came to do exactly this and can already see it. An indicator that fires
 * always is one people learn to ignore.
 *
 * Claims from two places because a hand-off produces two orderings. Arriving at
 * a different node remounts this after the request is made, so the mount claims
 * it; arriving at a node whose tab was ALREADY open does not remount at all, so
 * the request event claims it. Whichever runs first consumes the request.
 */
function PulseOnRequest({
    nodeId,
    children,
}: {
    nodeId: string;
    children: React.ReactNode;
}) {
    const ref = useRef<HTMLDivElement>(null);

    const pulseIfRequested = useCallback(() => {
        if (!claimPulse(credentialsPulseKey(nodeId)) || !ref.current) return;
        // Radius matches the wrapper's padding below, so the ring reads as a
        // region around the controls rather than a box ruled against the text.
        pulseElement(ref.current, { cycles: BANNER_PULSE_CYCLES, radius: 14 });
    }, [nodeId]);

    useEffect(pulseIfRequested, [pulseIfRequested]);
    useEffect(() => onPulseRequested(pulseIfRequested), [pulseIfRequested]);

    // Negative margin cancels the padding, so the ring gains breathing room from
    // the content without shifting the layout when it is not pulsing.
    return (
        <div ref={ref} data-credentials-area={nodeId} className="-m-2 p-2">
            {children}
        </div>
    );
}

export function CredentialsTabContent({
    selectedNode,
    nodeConfig,
    rawCredentialIds,
    credentialVariables,
    onCredentialChange,
}: CredentialsTabContentProps) {
    if (!selectedNode) {
        return <TabEmptyState message="Select a node to manage its credentials" />;
    }

    const nodeType = selectedNode.type || 'default';

    return (
        <div className="space-y-4">
            <div>
                <div className="text-[11px] text-muted-foreground dark:text-zinc-500 uppercase tracking-wider mb-1">
                    Node Type
                </div>
                <div className="text-sm text-foreground font-medium">
                    {nodeType}
                </div>
            </div>
            <PulseOnRequest nodeId={selectedNode.id}>
                <NodeCredentials
                    nodeType={nodeType}
                    nodeData={{
                        operation: selectedNode.data?.operation,
                        config: nodeConfig,
                    }}
                    credentialIds={rawCredentialIds}
                    onChange={onCredentialChange}
                    credentialVariables={credentialVariables}
                />
            </PulseOnRequest>
        </div>
    );
}
