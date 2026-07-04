// Single source of truth for CLI-harness brand-mark asset paths (from /public).
// These svg paths were previously copy-pasted across provider.tsx (PROVIDER_METADATA
// icons), nodeCatalog.server.ts (server-serialized harness marks), AgentModelIcon.tsx
// (agent-node wordmarks), AIAgentNode.tsx and credentialIcons.tsx — centralizing them
// here keeps the five surfaces from drifting when a mark is re-exported. Plain-string
// data only (no icon-component / registry imports), so it's safe to import from
// bundle-sensitive, always-mounted surfaces like the command palette. Brand COLORS
// intentionally stay in PROVIDER_METADATA (their single source); this holds paths only.

export type HarnessSlug = 'claude-code' | 'opencode' | 'openclaw' | 'hermes';

export interface HarnessBrand {
    /** Compact brand mark for small chrome — chips, dropdown rows, credential wells, badges. */
    markSrc: string;
    /** Full wordmark (logo + name) for large agent-node icons; absent = mark-only harness. */
    wordmarkSrc?: string;
    /** object-fit inset scale for full-bleed marks squeezed into a square badge (SerializedIcon). */
    inset?: number;
}

export const HARNESS_BRANDS: Record<HarnessSlug, HarnessBrand> = {
    'claude-code': { markSrc: '/icons/clawd.svg' },
    opencode: { markSrc: '/icons/opencode.svg', wordmarkSrc: '/icons/opencode-wordmark.svg', inset: 0.8 },
    openclaw: { markSrc: '/icons/openclaw_marker.svg', wordmarkSrc: '/icons/openclaw.svg' },
    hermes: { markSrc: '/icons/hermes_marker.svg', wordmarkSrc: '/icons/hermes.svg' },
};
