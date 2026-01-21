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
    pointerWithin,
    CollisionDetection,
    Collision,
} from '@dnd-kit/core';

interface DndProviderProps {
    children: ReactNode;
    overlay?: ReactNode;
    onDragStart?: (event: DragStartEvent) => void;
    onDragEnd?: (event: DragEndEvent) => void;
}

/**
 * Custom collision detection that prioritizes the most specific (smallest) droppable.
 * When multiple nested droppables contain the pointer, this returns them sorted
 * by bounding area (smallest first), ensuring the deepest/most specific droppable
 * is used for the drop target.
 */
const mostSpecificPointerWithin: CollisionDetection = (args) => {
    // Get all droppables where the pointer is within bounds
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
        >
            {children}
            <DragOverlay dropAnimation={null} zIndex={9999}>
                {overlay}
            </DragOverlay>
        </DndContext>
    );
}
