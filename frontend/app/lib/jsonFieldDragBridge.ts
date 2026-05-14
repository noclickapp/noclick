// Cross-tree bridge for JSON-field reference drags. FlowCanvas owns the
// dnd-kit DndContext where panel chips are draggable; consumers outside that
// tree (e.g. the agent ChatBox) can't register a useDroppable, so we mirror
// the drag through document-level DOM events. Constants live here so the two
// ends type-check against the same symbol instead of stringly-typed literals.

export const JSON_FIELD_DRAG_START_EVENT = 'noclick:json-field-drag-start';
export const JSON_FIELD_DRAG_END_EVENT = 'noclick:json-field-drag-end';

export interface JsonFieldDragDetail {
    nodeId: string;
    path: string;
    displayValue?: string;
}

export function dispatchJsonFieldDragStart(detail: JsonFieldDragDetail): void {
    document.dispatchEvent(new CustomEvent(JSON_FIELD_DRAG_START_EVENT, { detail }));
}

export function dispatchJsonFieldDragEnd(): void {
    document.dispatchEvent(new CustomEvent(JSON_FIELD_DRAG_END_EVENT));
}
