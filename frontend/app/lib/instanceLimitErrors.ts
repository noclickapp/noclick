/**
 * Predicates for backend plan/member-limit error strings.
 *
 * Kept separate from InstanceLimitDialog so
 * error-handling call sites don't import a component to classify an error.
 */

/** True for backend errors of the form "Instance limit reached: ...". */
export function isInstanceLimitError(error: string | null | undefined): boolean {
    if (!error) return false;
    return error.startsWith('Instance limit reached:');
}
