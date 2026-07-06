// Single source of truth for the ReactFlow canvas grid so every surface — the
// editor, the read-only viewer, the agent-scaffold auth preview, the marketing
// showcase — stays visually identical. Added after the style drifted (the editor
// was restyled but the read-only canvas kept the old gap/color).

import { Background, BackgroundVariant } from '@xyflow/react';

/** Dark-zinc canvas surface (tailwind zinc-950). Apply to the product canvases;
    the auth-page preview deliberately runs a touch lighter (#0f0f12). */
export const CANVAS_SURFACE = '#09090b';

export function CanvasBackground() {
    return <Background gap={14} size={1} color="#27272a" variant={BackgroundVariant.Cross} />;
}
