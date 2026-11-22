// The ReactFlow canvas grid every ReactFlow surface draws (the editor, the read-only viewer, the agent-scaffold auth
// preview, the marketing showcase), from the grid's one definition (@/ui/canvasGrid), which a CSS tile and the graph
// preview draw from too.

import { Background, BackgroundVariant } from '@xyflow/react';
import { CANVAS_GRID_COLOR, CANVAS_GRID_GAP, CANVAS_GRID_SIZE } from '@/ui/canvasGrid';

export function CanvasBackground() {
    return (
        <Background
            gap={CANVAS_GRID_GAP}
            size={CANVAS_GRID_SIZE}
            color={CANVAS_GRID_COLOR}
            variant={BackgroundVariant.Cross}
        />
    );
}
