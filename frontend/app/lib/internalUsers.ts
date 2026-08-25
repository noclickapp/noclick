// A self-hosted install must not inherit NoClick Cloud's staff identities.
// Keep this as a function (rather than deleting callers) so the shared UI keeps
// one stable seam while the hosted edition supplies its own implementation.
export const isInternalEmail = (_email: string): boolean => false;
