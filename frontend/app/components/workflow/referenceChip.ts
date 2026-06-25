// DOM-side chip element + shared chip styling for {{nodeId.path}} references.
// Split out from ReferenceHighlight.tsx so callers outside the workflow tree
// (e.g. ChatBox in the chat sidebar) can render a chip without pulling in
// ReferenceAutocompleteContext, which has its own dynamic-import dance to
// avoid an SSR circular dependency with nodeRegistry. Keeping this file
// dependency-free means it can be safely imported from any module graph.

// box-decoration-clone: when a chip wraps across lines, each line fragment gets its
// own rounded border + background instead of one box sliced open at the line break.
const CHIP_BASE = 'select-none rounded-sm border transition-colors box-decoration-clone';
const CHIP_VALID = 'bg-white/[0.08] border-white/[0.12] hover:bg-white/[0.14] hover:border-white/[0.2]';
const CHIP_INVALID = 'bg-red-500/20 border-red-500/40 hover:bg-red-500/30 hover:border-red-500/50';
// JS expression ({{ $('node').x.split(',') }}) — a slightly brighter neutral than a
// plain reference so it reads as "computed" without an off-theme accent color.
// Evaluated server-side, so never flagged invalid.
const CHIP_EXPRESSION = 'bg-white/[0.14] border-white/25 hover:bg-white/[0.2] hover:border-white/35';

export const REFERENCE_CHIP_CLASSES = {
    base: CHIP_BASE,
    valid: CHIP_VALID,
    invalid: CHIP_INVALID,
    expression: CHIP_EXPRESSION,
} as const;

// Build a styled, atomic chip element for inline use inside a contenteditable.
// `contenteditable="false"` keeps the chip atomic — the caret never lands
// inside it, and backspace removes the whole unit. `textContent` is the raw
// `{{nodeId.path}}` so extractContent (the contenteditable serializer) round-
// trips it back to the same reference string the backend expects.
export function createReferenceChipElement(reference: string): HTMLSpanElement {
    const span = document.createElement('span');
    span.setAttribute('contenteditable', 'false');
    span.dataset.reference = reference;
    span.className =
        'inline-flex items-center align-baseline px-1 mx-0.5 text-zinc-200 font-mono text-[12.5px] ' +
        `${CHIP_BASE} ${CHIP_VALID}`;
    span.textContent = reference;
    return span;
}
