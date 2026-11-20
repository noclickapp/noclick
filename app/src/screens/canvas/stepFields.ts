// The rules a step's fields are judged by: when a value is empty, when a field has a default, when the person must
// fill it, and the either-or groups (`x-require-one-of`) a step's schema declares. Shared by the canvas's validator
// and the step form, so the amber "needs one of these" hint and the run-blocking error never disagree.
import type { RequireOneOfGroups } from './stepSchema';

/**
 * Check if a field value is considered "empty" for validation purposes.
 */
export function isFieldEmpty(value: unknown): boolean {
    if (value === undefined || value === null) return true;
    if (typeof value === 'string' && value.trim() === '') return true;
    if (Array.isArray(value) && value.length === 0) return true;
    return false;
}

export interface SchemaFieldProp {
    default?: unknown;
    anyOf?: Array<{ type?: string }>;
    title?: string;
}

/**
 * Check if a field has a default value in its schema. Optional[T] (anyOf with
 * null) counts — the implicit None default means the backend won't reject the
 * node for omitting it.
 */
export function hasDefaultValue(fieldProp: SchemaFieldProp): boolean {
    if ('default' in fieldProp) return true;
    const anyOf = fieldProp.anyOf;
    if (anyOf && anyOf.some(t => t.type === 'null')) return true;
    return false;
}

/**
 * Single definition of "this field needs the user's attention" — true iff the
 * field is required, has no schema default, isn't an auto-set discriminator,
 * and the node's config value for it is empty.
 *
 * Both `validateNode` (drives `configValid` / the navigator pill / the auto-
 * consumers (the incomplete pill, the Setup tab's derived steps)
 * (drives the guided-setup wizard) route through this. Keeping the rule in one
 * place is what stops the pill and the Setup tab from disagreeing about
 * whether anything is left to fill.
 */
export interface SchemaField {
    key: string;
    required: boolean;
    prop: SchemaFieldProp;
}

/**
 * Single definition of "is this field something the user is responsible for
 * filling in?" — required, no schema default, and not the discriminator
 * (which is either hidden / backend-derived or surfaced as its own UX, never
 * as a regular required field).
 *
 * Pass the field name returned by `getDiscriminatorFieldName(nodeType)`; pass
 * `null` (or omit) for nodes without a discriminator.
 *
 * Deliberately answers ONLY the schema-shape question, not the live "is it
 * empty right now?" question. The two get composed at call sites:
 *   • validateNode → AND with isFieldEmpty (to flag missing required fields)
 *   • buildRequiredSteps → use this alone (to enumerate the wizard's steps)
 *   • isStepFilled → use isFieldEmpty alone on the already-built step
 * Keeping them separate is what stops the wizard step from vanishing mid-edit
 * the instant the user types a valid character.
 */
export function isFieldRequired(
    field: SchemaField,
    discriminatorField?: string | null,
): boolean {
    if (!field.required) return false;
    if (hasDefaultValue(field.prop)) return false;
    if (discriminatorField && field.key === discriminatorField) return false;
    return true;
}

export interface RequireOneOfResult {
    /** Groups where no alternative is fully satisfied. */
    unsatisfiedGroups: RequireOneOfGroups;
    /** Empty field keys belonging to an unsatisfied group — the ones to flag. */
    attentionKeys: Set<string>;
}

/**
 * Evaluate `x-require-one-of` groups against a config. A group is satisfied iff
 * some alternative has ALL its fields non-empty. Single source of truth for the
 * either-or rule, shared by the canvas validator and the config panel so the
 * amber "needs one of these" hint and the run-blocking error never disagree.
 */
export function evaluateRequireOneOf(
    groups: RequireOneOfGroups | undefined,
    config: Record<string, unknown>,
): RequireOneOfResult {
    const unsatisfiedGroups: RequireOneOfGroups = [];
    const attentionKeys = new Set<string>();
    if (!Array.isArray(groups)) return { unsatisfiedGroups, attentionKeys };

    for (const group of groups) {
        if (!Array.isArray(group) || group.length === 0) continue;
        const satisfied = group.some(
            alt => Array.isArray(alt) && alt.length > 0 && alt.every(k => !isFieldEmpty(config[k])),
        );
        if (!satisfied) {
            unsatisfiedGroups.push(group);
            for (const alt of group) {
                for (const k of alt) {
                    if (isFieldEmpty(config[k])) attentionKeys.add(k);
                }
            }
        }
    }
    return { unsatisfiedGroups, attentionKeys };
}

/**
 * Human-readable description of a require-one-of group, e.g.
 * "Video ID or Address" or "Region Place ID or Latitude + Longitude + Radius".
 */
export function describeRequireOneOfGroup(
    group: string[][],
    titleOf: (key: string) => string,
): string {
    return group.map(alt => alt.map(titleOf).join(' + ')).join(' or ');
}
