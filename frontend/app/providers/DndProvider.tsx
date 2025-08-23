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
} from '@dnd-kit/core';

interface DndProviderProps {
    children: ReactNode;
    overlay?: ReactNode;
    onDragStart?: (event: DragStartEvent) => void;
    onDragEnd?: (event: DragEndEvent) => void;
}

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

    // If you want collision detection:
    //   collisionDetection={closestCenter}
    return (
        <DndContext
            sensors={sensors}
            collisionDetection={pointerWithin}
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
