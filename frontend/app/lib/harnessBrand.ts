// Single source of truth for CLI-harness brand-mark asset paths (from /public).
// These svg paths were previously copy-pasted across provider.tsx (PROVIDER_METADATA
// icons), nodeCatalog.server.ts (server-serialized harness marks), AgentModelIcon.tsx
// (agent-node wordmarks), AIAgentNode.tsx and credentialIcons.tsx — centralizing them
// here keeps the five surfaces from drifting when a mark is re-exported. Plain-string
// data only (no icon-component / registry imports), so it's safe to import from
// bundle-sensitive, always-mounted surfaces like the command palette. Brand COLORS
// intentionally stay in PROVIDER_METADATA (their single source); this holds paths only.

export type HarnessSlug = 'claude-code' | 'opencode' | 'openclaw' | 'hermes';

export type AgentModelKind = HarnessSlug | 'codex' | 'bot';

/** Maps an agent node's `model` config value to the logo it renders. The CLI
 *  harnesses (and Hermes models) get brand marks; everything else falls back to
 *  the generic Bot glyph. Lives here (not AgentModelIcon) so data-layer modules
 *  can classify without importing icon components. */
export function resolveAgentModelKind(model: string): AgentModelKind {
    if (model === 'codex') return 'codex';
    if (model === 'claude-code') return 'claude-code';
    if (model === 'opencode') return 'opencode';
    if (model === 'openclaw') return 'openclaw';
    if (model.includes('hermes') || model.includes('nousresearch'))
        return 'hermes';
    return 'bot';
}

/** The icon-registry key for an agent node running `model`.
 *
 *  The dashboard loader serializes a synthetic `agent:<harness>` entry per CLI
 *  harness so light surfaces can show the mark the agent actually runs under
 *  without importing brand components. API-model agents keep the generic
 *  `agent` icon, which is also where an unknown kind lands. Shared by the
 *  workflow-browser icon rows and the Run popup's entry-point screen — an
 *  agent that renders as a generic robot next to its own message reads as the
 *  wrong node. */
export function agentIconType(model: string | undefined | null): string {
    const kind = resolveAgentModelKind(model ?? '');
    return kind === 'bot' ? 'agent' : `agent:${kind}`;
}

export interface HarnessBrand {
    /** Compact brand mark for small chrome — chips, dropdown rows, credential wells, badges. */
    markSrc: string;
    /** Full wordmark (logo + name) for large agent-node icons; absent = mark-only harness. */
    wordmarkSrc?: string;
    /** Visual-weight scale applied to the mark inside a square badge (SerializedIcon):
     *  <1 insets full-bleed marks, >1 grows marks whose contain-fit renders small
     *  (e.g. clawd is wider than tall, so height-fitting leaves it undersized). */
    inset?: number;
    /** Art is pure white (drawn for dark backgrounds). Consumers rendering it on a
     *  themed surface must invert it in light mode (`invert dark:invert-0`) so it
     *  reads as a dark glyph on light and stays white on dark; the dark-well chips
     *  that already sit on a fixed dark circle leave it as-is. */
    monochrome?: boolean;
}

export const HARNESS_BRANDS: Record<HarnessSlug, HarnessBrand> = {
    // NOTE: bare icon rows (workflow-card pill) now size <img> marks by intrinsic
    // aspect, so wide marks like clawd no longer need big compensating insets.
    // clawd.svg is colored (#c97c5d salmon) → visible on both themes.
    'claude-code': { markSrc: '/icons/clawd.svg', inset: 1.1 },
    // opencode marks are two-tone gray (#4B4646 / #F1ECEC) → self-adapting, no invert.
    opencode: {
        markSrc: '/icons/opencode.svg',
        wordmarkSrc: '/icons/opencode-wordmark.svg',
        inset: 0.9,
    },
    // openclaw marker + wordmark are pure-white dark-bg art → invert in light mode.
    openclaw: {
        markSrc: '/icons/openclaw_marker.svg',
        wordmarkSrc: '/icons/openclaw.svg',
        monochrome: true,
    },
    // hermes marks are gold/amber/bronze (#FFD700…) → visible on both themes.
    hermes: {
        markSrc: '/icons/hermes_marker.svg',
        wordmarkSrc: '/icons/hermes.svg',
        inset: 0.95,
    },
};
