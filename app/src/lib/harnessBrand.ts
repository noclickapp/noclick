// Single source of truth for the coding harnesses' brand-mark asset paths (served from /public), so every surface
// that draws one (chips, the agent node, a workflow's preview, the marks a node catalog serializes) shows the same
// asset. Plain-string data only (no icon components or registries), so it's safe to import from bundle-sensitive,
// always-mounted surfaces like a command palette. Brand colours live with each provider's own metadata; this holds
// paths only.

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
 *  A node catalog serializes a synthetic `agent:<harness>` entry per CLI
 *  harness so light surfaces can show the mark the agent actually runs under
 *  without importing brand components. API-model agents keep the generic
 *  `agent` icon, which is also where an unknown kind lands: an agent that
 *  renders as a generic robot next to its own message reads as the wrong node. */
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

// Claude Code uses its compact mark (no wordmark); the others use their full wordmark. The agent node and a workflow's
// preview draw the same assets.
export const IMG_META: Record<Exclude<AgentModelKind, 'codex' | 'bot'>, { src: string; alt: string }> = {
    'claude-code': { src: HARNESS_BRANDS['claude-code'].markSrc, alt: 'Claude Code' },
    opencode: { src: HARNESS_BRANDS.opencode.wordmarkSrc!, alt: 'OpenCode' },
    openclaw: { src: HARNESS_BRANDS.openclaw.wordmarkSrc!, alt: 'OpenClaw' },
    hermes: { src: HARNESS_BRANDS.hermes.wordmarkSrc!, alt: 'Hermes' },
};
