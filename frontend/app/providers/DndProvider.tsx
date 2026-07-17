// DndProvider wraps dnd-kit's DndContext with custom collision detection.
// Uses a custom collision algorithm that prioritizes the most specific droppable
// (smallest bounding area) when multiple nested droppables contain the pointer.

import { ReactNode } from 'react';
import {
    DndContext,
    DragEndEvent,
    DragStartEvent,
    DragOverlay,
    PointerSensor,
    useSensor,
    useSensors,
    closestCenter,
    pointerWithin,
    rectIntersection,
    CollisionDetection,
    Collision,
} from '@dnd-kit/core';
import { CANVAS_DROP_KINDS } from '~/lib/canvasDropKinds';

interface DndProviderProps {
    children: ReactNode;
    overlay?: ReactNode;
    onDragStart?: (event: DragStartEvent) => void;
    onDragEnd?: (event: DragEndEvent) => void;
    autoScroll?: boolean;
}

/**
 * Custom collision detection that prioritizes the most specific (smallest) droppable.
 * When multiple nested droppables contain the pointer, this returns them sorted
 * by bounding area (smallest first), ensuring the deepest/most specific droppable
 * is used for the drop target.
 */
const mostSpecificPointerWithin: CollisionDetection = (args) => {
    // Canvas wiring targets (agent body, edge "+", node tail "+") hit when the
    // DRAGGED NODE overlaps them, not when the cursor does — the "+" boxes are
    // ~40px and far too small to aim a cursor at. Among the ones the node
    // overlaps, the nearest to the node's centre wins, so clipping the corner of
    // a distant "+" never beats the one you're actually over.
    const canvasTargets =
        args.active.data.current?.type === 'workflow-node'
            ? args.droppableContainers.filter((c) =>
                  CANVAS_DROP_KINDS.has(c.data.current?.type as string)
              )
            : [];
    if (canvasTargets.length > 0) {
        const overlapping = rectIntersection({
            ...args,
            droppableContainers: canvasTargets,
        });
        if (overlapping.length > 0) {
            // Smallest target wins, same as the pointer path below: a node's tail
            // "+" sits right beside its node, so a big agent body would otherwise
            // swallow the small, more specific "+" next to it. Ties (equal-size
            // targets, e.g. two edge "+"s) break on distance to the node's centre.
            const area = (c: Collision) => {
                const rect = c.data?.droppableContainer?.rect?.current;
                return rect ? rect.width * rect.height : Number.MAX_SAFE_INTEGER;
            };
            const smallest = Math.min(...overlapping.map(area));
            const finalists = new Set(
                overlapping.filter((c) => area(c) === smallest).map((c) => c.id)
            );
            return closestCenter({
                ...args,
                droppableContainers: canvasTargets.filter((c) =>
                    finalists.has(c.id)
                ),
            });
        }
    }

    // Everything else (config fields, folders, the helper view) stays
    // pointer-driven: those are precise, cursor-sized interactions.
    const collisions = pointerWithin(args);

    if (collisions.length <= 1) {
        return collisions;
    }

    // Sort by bounding area (smallest first) to prioritize the most specific droppable
    // This ensures nested droppables (like config fields inside the helper view)
    // take priority over their parent containers
    return [...collisions].sort((a: Collision, b: Collision) => {
        const rectA = a.data?.droppableContainer?.rect?.current;
        const rectB = b.data?.droppableContainer?.rect?.current;

        if (!rectA || !rectB) return 0;

        const areaA = rectA.width * rectA.height;
        const areaB = rectB.width * rectB.height;

        return areaA - areaB; // Smallest area first
    });
};

/**
 * Lightweight wrapper around DndContext
 * that triggers onDragStart / onDragEnd to the parent.
 */
export function DndProvider({
    children,
    overlay,
    onDragStart,
    onDragEnd,
    autoScroll = true,
}: DndProviderProps) {
    // Set up sensors
    const sensors = useSensors(
        useSensor(PointerSensor, { activationConstraint: { distance: 0 } })
    );

    return (
        <DndContext
            sensors={sensors}
            collisionDetection={mostSpecificPointerWithin}
            onDragStart={onDragStart}
            onDragEnd={onDragEnd}
            autoScroll={autoScroll}
        >
            {children}
            <DragOverlay dropAnimation={null} zIndex={9999}>
                {overlay}
            </DragOverlay>
        </DndContext>
    );
}
