// Resolve the integration node (brand icon + color) behind a
// "{provider}__{operation}" agent-tool slug, so every surface that renders tool
// calls (feed rows, the chat's step timeline) shows the same mark the canvas
// does. Read from the serialized icon catalog (lib/nodeIconRegistry), never the
// node registry: the chat transcript is on the first paint of the dashboard and
// of public agent pages, and the registry carries every node component.

import { getNodeIconMeta } from '~/lib/nodeIconRegistry';
import type { SerializedNodeMeta } from '~/lib/nodeCatalogTypes';

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
): SerializedNodeMeta | undefined {
    const candidates = providerTypeCandidates(toolName);
    if (providerNodeType) candidates.unshift(providerNodeType);
    for (const type of candidates) {
        const meta = getNodeIconMeta(type);
        if (meta?.iconHtml) return meta;
    }
    return undefined;
}

/** Agent tools that come with every agent rather than from an integration. */
const BUILTIN_TOOL_LABELS: Record<string, string> = {
    web_search: 'Web search',
    web_fetch: 'Fetch pages',
    execute_bash: 'Shell',
};

/** A tool as a compact chip shows it: the node type for its mark (null for a
 *  built-in tool), the integration's name, and what the call did ("Create
 *  refund"), from the icon catalog NodeMark draws from. */
export function toolIntegration(toolName: string): { type: string | null; provider: string; action: string } {
    const [slug, ...rest] = toolName.split('__');
    const operation = rest.join('__').replace(/_/g, ' ').trim();
    const meta = resolveToolProviderMeta(toolName);
    const type = meta?.type ?? null;
    const provider = meta?.label ?? BUILTIN_TOOL_LABELS[toolName] ?? slug.replace(/[_-]+/g, ' ').replace(/^\w/, (c) => c.toUpperCase());
    return { type, provider, action: operation ? operation.charAt(0).toUpperCase() + operation.slice(1) : provider };
}
