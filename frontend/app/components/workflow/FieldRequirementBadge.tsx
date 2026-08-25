// Shared Required/Optional pill for form field labels, extracted from NodeConfig
// so lightweight surfaces (the credential forms, including the public
// credential-provide page) can reuse it without pulling in NodeConfig's heavy
// module graph (AJV, the widget registry).

// Inline pill that sits next to a field label. Replaces the old red `*` —
// makes the required/optional distinction obvious at a glance without
// relying on a single easy-to-miss character. The required treatment uses
// amber to match the "Guided Setup" pill that surfaces incomplete required
// fields at the top of the canvas. Once a required field is filled the badge
// drops to the same neutral treatment as Optional so it stops competing for
// attention — only unsatisfied required fields stay amber.
export function FieldRequirementBadge({ isRequired, isFilled = false }: { isRequired: boolean; isFilled?: boolean }) {
    const neutralClass = 'bg-muted dark:bg-zinc-800/60 text-muted-foreground dark:text-zinc-500 ring-1 ring-inset ring-border/60 dark:ring-zinc-700/50';
    const amberClass = 'bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-400 ring-1 ring-inset ring-amber-300 dark:ring-amber-500/40';
    const showAmber = isRequired && !isFilled;
    return (
        <span
            className={`inline-flex items-center px-1.5 py-px text-[9px] font-medium uppercase tracking-wide rounded ${
                showAmber ? amberClass : neutralClass
            }`}
        >
            {isRequired ? 'Required' : 'Optional'}
        </span>
    );
}

// Mirrors NodeConfig's post-AJV "required string is empty" check: a field counts
// as filled when it has a value that isn't an empty/whitespace string.
export function isFieldFilled(value: unknown): boolean {
    if (value === undefined || value === null) return false;
    if (typeof value === 'string') return value.trim() !== '';
    if (Array.isArray(value)) return value.length > 0;
    if (typeof value === 'object') return Object.keys(value as object).length > 0;
    return true;
}
