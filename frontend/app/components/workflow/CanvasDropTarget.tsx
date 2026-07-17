// A dnd-kit drop target for the canvas, deliberately isolated in its own leaf
// component. dnd-kit's InternalContext value changes on every over-transition,
// so every useDroppable consumer re-renders then — keeping the hook here means
// that churn never reaches the (expensive) edge and node bodies that host these
// targets. Added so palette nodes can be dropped straight onto an agent, an
// edge's "+", or a node's trailing "+" instead of only onto bare canvas.

import { useDroppable } from '@dnd-kit/core';
import type { CSSProperties, ReactNode } from 'react';
import type { CanvasDropKind } from '~/lib/canvasDropKinds';

interface CanvasDropTargetProps {
    id: string;
    kind: CanvasDropKind;
    /** Merged into the droppable's data alongside `type: kind`. */
    payload: Record<string, unknown>;
    /** Node types this target can't accept — drops fall through to a plain
     *  canvas placement, and no hover affordance is shown. */
    accepts?: (nodeType: string) => boolean;
    className?: string;
    style?: CSSProperties;
    /** Rendered with the live hover state so the host can show an affordance. */
    children?: (state: { isOver: boolean; isCandidate: boolean }) => ReactNode;
}

export function CanvasDropTarget({
    id,
    kind,
    payload,
    accepts,
    className,
    style,
    children,
}: CanvasDropTargetProps) {
    const { setNodeRef, isOver, active } = useDroppable({
        id,
        data: { type: kind, ...payload },
    });

    // `active` rides the same context read useDroppable already does, so gating
    // the affordance on the dragged node's type costs no extra subscription.
    const draggedType =
        active?.data?.current?.type === 'workflow-node'
            ? (active.data.current.nodeType as string | undefined)
            : undefined;
    const isCandidate = !!draggedType && (!accepts || accepts(draggedType));

    return (
        <div ref={setNodeRef} className={className} style={style}>
            {children?.({ isOver: isOver && isCandidate, isCandidate })}
        </div>
    );
}
