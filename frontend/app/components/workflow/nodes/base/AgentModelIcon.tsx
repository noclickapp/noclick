// AgentModelIcon — single source of truth for the brand logo an AI agent node
// shows for its selected model (Codex/OpenAI, Claude Code, OpenCode, OpenClaw,
// Hermes, or the generic Bot fallback). Shared by the desktop AIAgentNode and the
// xyflow-free ForkCanvas agent card so the model → logo mapping (and its bespoke
// per-logo sizing) lives in ONE place and the two canvases can't drift. Pure +
// props-only — no hooks, no store reads.

import type { CSSProperties } from 'react';
import { Bot } from 'lucide-react';
import { OpenAI } from '@lobehub/icons';

export type AgentModelKind = 'codex' | 'claude-code' | 'opencode' | 'openclaw' | 'hermes' | 'bot';

const CLAUDE_CODE_ICON_SRC = '/icons/clawd.svg';
const OPENCODE_ICON_SRC = '/icons/opencode-wordmark.svg';
const OPENCLAW_ICON_SRC = '/icons/openclaw.svg';
const HERMES_ICON_SRC = '/icons/hermes.svg';

/** Maps an agent node's `model` config value to the logo it renders. The CLI
 *  harnesses get bespoke wordmarks; everything else falls back to the Bot glyph. */
export function resolveAgentModelKind(model: string): AgentModelKind {
    if (model === 'codex') return 'codex';
    if (model === 'claude-code') return 'claude-code';
    if (model === 'opencode') return 'opencode';
    if (model === 'openclaw') return 'openclaw';
    if (model.includes('hermes') || model.includes('nousresearch')) return 'hermes';
    return 'bot';
}

const DROP_SHADOW_NORMAL = 'drop-shadow(0 4px 12px rgba(0, 0, 0, 0.4))';
const DROP_SHADOW_COMPACT = 'drop-shadow(0 2px 6px rgba(0, 0, 0, 0.4))';
const DISABLED_FILTER = `grayscale(100%) brightness(0.4) ${DROP_SHADOW_NORMAL}`;

// Intrinsic sizing per kind × variant — copied verbatim from the previous inline
// AIAgentNode render so the desktop look is unchanged. img wordmarks size by a
// single axis (the other stays auto); the icon components size both.
const SIZES: Record<AgentModelKind, { normal: CSSProperties; compact: CSSProperties }> = {
    codex: { normal: { width: 40, height: 40 }, compact: { width: 32, height: 32 } },
    'claude-code': { normal: { height: 40 }, compact: { height: 32 } },
    opencode: { normal: { height: 22 }, compact: { height: 18 } },
    openclaw: { normal: { width: 148, height: 'auto' }, compact: { width: 60, height: 'auto' } },
    hermes: { normal: { height: 26 }, compact: { height: 20 } },
    bot: { normal: { width: 40, height: 40 }, compact: { width: 32, height: 32 } },
};

const IMG_META: Record<Exclude<AgentModelKind, 'codex' | 'bot'>, { src: string; alt: string }> = {
    'claude-code': { src: CLAUDE_CODE_ICON_SRC, alt: 'Claude Code' },
    opencode: { src: OPENCODE_ICON_SRC, alt: 'OpenCode' },
    openclaw: { src: OPENCLAW_ICON_SRC, alt: 'OpenClaw' },
    hermes: { src: HERMES_ICON_SRC, alt: 'Hermes' },
};

interface AgentModelIconProps {
    model: string;
    /** 'normal' = the agent node's main icon; 'compact' = the AI-editing-state icon. */
    variant?: 'normal' | 'compact';
    /** Greys out + dims the logo (mirrors the desktop disabled-node treatment). */
    disabled?: boolean;
    /** Extra caller-owned state classes (selection / hover / transition). The
     *  per-kind color + disabled opacity are owned by this component. */
    stateClassName?: string;
}

export function AgentModelIcon({ model, variant = 'normal', disabled = false, stateClassName = '' }: AgentModelIconProps) {
    const kind = resolveAgentModelKind(model);
    const style: CSSProperties = {
        ...SIZES[kind][variant],
        filter: disabled ? DISABLED_FILTER : (variant === 'normal' ? DROP_SHADOW_NORMAL : DROP_SHADOW_COMPACT),
    };

    if (kind === 'codex') {
        return <OpenAI className={`${disabled ? 'opacity-35' : 'text-white'} ${stateClassName}`.trim()} style={style} />;
    }
    if (kind === 'bot') {
        return <Bot className={`${disabled ? 'opacity-35' : 'text-purple-400'} ${stateClassName}`.trim()} style={style} />;
    }
    const { src, alt } = IMG_META[kind];
    return <img src={src} alt={alt} className={`${disabled ? 'opacity-35' : ''} ${stateClassName}`.trim()} style={style} />;
}
