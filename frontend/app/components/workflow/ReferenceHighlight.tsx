// Shared rendering for inline {{nodeId.path}} reference chips.
//
// Two call sites use the same visual treatment for inserted references:
//   1. DroppableTextField (config fields under FlowHelperView) — overlay
//      layer drawn on top of a <textarea>/<input>.
//   2. ChatBox (agent sidebar contenteditable) — inline DOM element inserted
//      directly into the editor at the cursor.
//
// Case 1 uses the React overlay component; case 2 uses the
// `createReferenceChipElement` DOM helper because contenteditable can't host
// a React-controlled subtree without a portal scaffold. Parsing, validation,
// and the chip styling are common to both.

import { useEffect, useLayoutEffect, useMemo, useRef, type RefObject } from 'react';
import { useReferenceAutocomplete, extractAllReferences } from './ReferenceAutocompleteContext';
import { REFERENCE_CHIP_CLASSES } from './referenceChip';
import { scanBlocks, isJsExpression, parsePureAccessor } from './expressionSyntax';

export interface TextSegment {
    type: 'text';
    content: string;
    startIndex: number;
}

export interface ReferenceSegment {
    type: 'reference';
    content: string;
    nodeId: string;
    path: string;
    startIndex: number;
    isValid?: boolean;
}

export interface ExpressionSegment {
    type: 'expression';
    content: string;
    inner: string;
    startIndex: number;
}

export type Segment = TextSegment | ReferenceSegment | ExpressionSegment;

// Parse a string into alternating text / reference / expression segments. A block
// using a `$`-accessor is an expression (evaluated server-side); a dotted path is a
// legacy reference; anything else (incl. no-dot blocks like `{{name}}`) stays text so
// we don't render a misleading chip. Brace/string-aware so JS with inner `}` parses.
export function parseValueIntoSegments(value: string): Segment[] {
    if (typeof value !== 'string') return [];
    const segments: Segment[] = [];
    let lastIndex = 0;

    for (const block of scanBlocks(value)) {
        if (block.start > lastIndex) {
            segments.push({ type: 'text', content: value.slice(lastIndex, block.start), startIndex: lastIndex });
        }
        const fullRef = value.slice(block.start, block.end);
        const inner = block.inner.trim();
        const pureAccessor = isJsExpression(inner) ? parsePureAccessor(inner) : null;
        if (isJsExpression(inner) && !pureAccessor) {
            // Has a transform (call/operator) — a real expression.
            segments.push({ type: 'expression', content: fullRef, inner, startIndex: block.start });
        } else if (pureAccessor) {
            // `$('node').field` with no transform — semantically a reference.
            segments.push({
                type: 'reference',
                content: fullRef,
                nodeId: pureAccessor.nodeId,
                path: pureAccessor.path,
                startIndex: block.start,
            });
        } else {
            const dotIndex = inner.indexOf('.');
            if (dotIndex > 0) {
                segments.push({
                    type: 'reference',
                    content: fullRef,
                    nodeId: inner.slice(0, dotIndex),
                    path: inner.slice(dotIndex + 1),
                    startIndex: block.start,
                });
            } else {
                segments.push({ type: 'text', content: fullRef, startIndex: block.start });
            }
        }
        lastIndex = block.end;
    }

    if (lastIndex < value.length) {
        segments.push({ type: 'text', content: value.slice(lastIndex), startIndex: lastIndex });
    }

    return segments;
}

// Parse + cross-check each reference against the autocomplete validator
// (which knows the live workflow graph). Returns `isValid` per reference.
export function useReferenceSegments(value: string): { segments: Segment[]; hasReferences: boolean; invalidReferences: Set<string> } {
    const autocompleteContext = useReferenceAutocomplete();

    const invalidReferences = useMemo(() => {
        if (!autocompleteContext || !value) return new Set<string>();
        const invalid = new Set<string>();
        for (const ref of extractAllReferences(value)) {
            const result = autocompleteContext.validateReference(ref);
            if (!result.valid) invalid.add(`{{${ref}}}`);
        }
        return invalid;
    }, [autocompleteContext, value]);

    const segments = useMemo<Segment[]>(() => {
        const parsed = parseValueIntoSegments(value);
        return parsed.map((segment) =>
            segment.type === 'reference'
                ? { ...segment, isValid: !invalidReferences.has(segment.content) }
                : segment,
        );
    }, [value, invalidReferences]);

    const hasReferences = segments.some((s) => s.type === 'reference' || s.type === 'expression');

    return { segments, hasReferences, invalidReferences };
}

const { base: CHIP_BASE, valid: CHIP_VALID, invalid: CHIP_INVALID, expression: CHIP_EXPRESSION } = REFERENCE_CHIP_CLASSES;

interface ReferenceHighlightOverlayProps {
    value: string;
    // Pass the textarea/input's padding+font classes so the overlay's invisible
    // text wraps and aligns pixel-for-pixel with the real input below it.
    inputClassName: string;
    multiline?: boolean;
    // Suppress the "invalid" red treatment while the user is mid-keystroke so
    // it doesn't flash for half-typed references.
    isEditing?: boolean;
    // Extra Tailwind classes — e.g. `pr-8` when the parent reserves trailing
    // space for an indicator icon.
    extraClassName?: string;
    // The textarea/input element whose `scrollTop`/`scrollLeft` we mirror so
    // chips don't desync from the underlying text when the input scrolls.
    // Without this, an overflowed multi-line field shows chips frozen at the
    // top even after the user scrolls down.
    scrollRef?: RefObject<HTMLTextAreaElement | HTMLInputElement | null>;
}

// Absolute-positioned overlay that draws reference chips on top of a textarea
// or input. The outer wrapper sits flush with the input and clips overflow;
// the inner layout layer carries the input's padding/font so the invisible
// text segments wrap exactly like the real text, then gets translated to
// match the input's scroll position.
export function ReferenceHighlightOverlay({
    value,
    inputClassName,
    multiline = false,
    isEditing = false,
    extraClassName = '',
    scrollRef,
}: ReferenceHighlightOverlayProps) {
    const { segments, hasReferences } = useReferenceSegments(value);
    const innerRef = useRef<HTMLDivElement>(null);

    // Keep the chip layer aligned with the input's scroll. We mutate
    // `transform` imperatively to dodge a re-render on every wheel tick — the
    // sync runs in a passive scroll listener and a useLayoutEffect for the
    // post-render catch-up (value changes can push scrollTop without firing a
    // scroll event).
    const syncScroll = () => {
        const inner = innerRef.current;
        const scroller = scrollRef?.current;
        if (!inner || !scroller) return;
        inner.style.transform = `translate(${-scroller.scrollLeft}px, ${-scroller.scrollTop}px)`;
    };

    useLayoutEffect(() => {
        syncScroll();
    });

    useEffect(() => {
        const scroller = scrollRef?.current;
        if (!scroller) return;
        scroller.addEventListener('scroll', syncScroll, { passive: true });
        return () => scroller.removeEventListener('scroll', syncScroll);
        // syncScroll closes over refs only; reattaching on each render is wasteful.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [scrollRef]);

    if (!hasReferences) return null;

    return (
        <div className="absolute inset-0 pointer-events-none overflow-hidden rounded-lg">
            <div
                ref={innerRef}
                // extraClassName (the `pr-8` indicator gutter) goes on the INNER text
                // layer, NOT the outer wrapper — on the wrapper it would shrink this div
                // AND stack with px-3's right padding, making the text box ~12px narrower
                // than the textarea so chips wrap a column early. Here it matches exactly.
                className={`${inputClassName} ${extraClassName}`}
                style={{
                    whiteSpace: multiline ? 'pre-wrap' : 'nowrap',
                    // Match the textarea's wrapping exactly (it uses word-break: normal +
                    // overflow-wrap: break-word). `word-break: break-word` here breaks a
                    // reference at a different point, so the chip background desyncs from
                    // the text underneath — landing the highlight on the wrong line.
                    wordBreak: 'normal',
                    overflowWrap: 'break-word',
                    willChange: 'transform',
                }}
            >
                {segments.map((segment, index) => {
                    if (segment.type === 'text') {
                        return (
                            <span key={index} className="opacity-0 select-none" aria-hidden="true">
                                {segment.content}
                            </span>
                        );
                    }
                    if (segment.type === 'expression') {
                        // Evaluated server-side, so never "invalid" here; distinct violet hue.
                        return (
                            <span
                                key={index}
                                className={`text-transparent ${CHIP_BASE} ${CHIP_EXPRESSION}`}
                                title={`Expression: ${segment.inner}`}
                            >
                                {segment.content}
                            </span>
                        );
                    }
                    const isInvalid = !segment.isValid && !isEditing;
                    const stateClass = isInvalid ? CHIP_INVALID : CHIP_VALID;
                    // Visual only (pointer-events: none from the overlay container) so a
                    // click falls through to the textarea and the caret lands where you
                    // clicked, instead of snapping to the end of the reference.
                    return (
                        <span
                            key={index}
                            className={`text-transparent ${CHIP_BASE} ${stateClass}`}
                            title={isInvalid ? `Invalid reference: ${segment.nodeId}.${segment.path}` : undefined}
                        >
                            {segment.content}
                        </span>
                    );
                })}
            </div>
        </div>
    );
}

