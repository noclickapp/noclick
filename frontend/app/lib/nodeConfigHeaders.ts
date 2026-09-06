// Per-node-type header rendered above a node's config form in the helper
// panel (FlowHelperView). The engine ships with no registrations; the hosted
// bootstrap (app/cloud/bootstrap.ts) registers the surfaces the hosted
// service adds — the MCP node's "Connect externally" hosted-link panel — so
// shipped code never names a hosted module (same seam pattern as
// lib/runResults.registerRunStoryEnricher).
import type { ComponentType } from 'react';

export interface NodeConfigHeaderProps {
    workflowId: string;
    nodeId: string;
    nodeLabel?: string;
}

const headers = new Map<string, ComponentType<NodeConfigHeaderProps>>();

export function registerNodeConfigHeader(
    nodeType: string,
    Header: ComponentType<NodeConfigHeaderProps>
): void {
    headers.set(nodeType, Header);
}

export function getNodeConfigHeader(
    nodeType: string | undefined
): ComponentType<NodeConfigHeaderProps> | undefined {
    return nodeType ? headers.get(nodeType) : undefined;
}
