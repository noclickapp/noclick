// Each droppable field's way to insert a reference at its cursor, by field key: what a drop on the field, the step form's
// "Add reference" and a sibling field (SearchableEnumField) reach it by. Kept apart from the fields that register in it,
// so a hot reload of one of them leaves it as it is.

// Stores a ref wrapper so we can update the function without registry churn
export interface InsertReferenceRef {
    fn: (reference: string) => void;
}

export const insertReferenceRegistry = new Map<string, InsertReferenceRef>();
