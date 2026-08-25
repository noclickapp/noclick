/**
 * Predicates for backend plan/member-limit error strings.
 *
 * Kept separate from the compatibility limit dialog so error-handling call
 * sites don't import a component to classify an error.
 */

/** True for backend errors of the form "Plan limit reached: ...". */
export function isPlanLimitError(error: string | null | undefined): boolean {
    if (!error) return false;
    return error.startsWith('Plan limit reached:');
}

/** True for org-member limit errors (raised by the member-limit DB trigger). */
export function isMemberLimitError(error: string | null | undefined): boolean {
    if (!error) return false;
    return error.toLowerCase().includes('member limit');
}

/** True if the error should trigger the compatibility limit dialog. */
export function isUpgradeRequiredError(
    error: string | null | undefined
): boolean {
    return isPlanLimitError(error) || isMemberLimitError(error);
}
