// Resolve the integration node (registry metadata: brand icon + color) behind
// a "{provider}__{operation}" agent-tool slug. Extracted from the Feed's
// Agents tab so every surface that renders tool calls (feed rows, the chat's
// step timeline) shows the same mark the canvas does.

import { getNodeMetadata } from '~/components/workflow/nodes/nodeRegistry';

// Candidate node types from a tool name "{provider}__{operation}". The provider
// slug is snake_case while node types are hyphenated ("google_sheets" →
// "automation-google-sheets"). Co-resident same-type providers get a dedup
// suffix ("http_request_e0x5"), so also try the slug with its trailing segment
// dropped ("http_request") as a fallback.
export function providerTypeCandidates(toolName: string): string[] {
    const slug = toolName.includes('__') ? toolName.split('__')[0] : '';
    if (!slug) return [];
    const candidates = [`automation-${slug.replace(/_/g, '-')}`];
    const parts = slug.split('_');
    if (parts.length > 1)
        candidates.push(`automation-${parts.slice(0, -1).join('-')}`);
    return candidates;
}

// Resolve the integration node behind a tool — by the provider node's resolved
// registry type when known, else reconstructed from the tool name. Returns
// only a match that actually has an icon.
export function resolveToolProviderMeta(
    toolName: string,
    providerNodeType?: string | null
) {
    if (providerNodeType) {
        const m = getNodeMetadata(providerNodeType);
        if (m?.Icon) return m;
    }
    for (const t of providerTypeCandidates(toolName)) {
        const m = getNodeMetadata(t);
        if (m?.Icon) return m;
    }
    return undefined;
}
