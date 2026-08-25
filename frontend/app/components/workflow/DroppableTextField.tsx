// DroppableTextField component is a text input that accepts dropped JSON field references.
// When a draggable JSON field is dropped, it inserts a reference like {{nodeId.path}}.
// The backend resolves these references during workflow execution.
// Hovering over references highlights the corresponding field in the Input panel.
// Provides autocomplete when typing inside {{}} with validation for invalid references.

import { useRef, useState, useCallback, useEffect, useLayoutEffect, type CSSProperties } from 'react';
import { useDroppable } from '@dnd-kit/core';
import { Link2, X, AlertCircle } from 'lucide-react';
import { cn } from '~/lib/utils';
import { useReferenceAutocomplete } from './ReferenceAutocompleteContext';
import { useReferenceHover } from './ReferenceHoverContext';
import { ReferenceHighlightOverlay, useReferenceSegments } from './ReferenceHighlight';
import { scanBlocks, pathToExpression, blockAtCursor, referenceAtCursor } from './expressionSyntax';
import { ExpressionPanel } from './ExpressionPanel';

interface DroppableTextFieldProps {
    value: string;
    onChange: (value: string) => void;
    placeholder?: string;
    multiline?: boolean;
    rows?: number; // Minimum rows for multiline (default: 2)
    autoExpand?: boolean; // Auto-expand textarea height (default: true for multiline)
    className?: string;
    fieldKey: string; // Unique identifier for this field (used for droppable ID)
    hasError?: boolean; // Whether this field has execution errors (shows red border)
}

// Extend HTMLElement to include the insertReference method for drop handling
interface ExtendedHTMLElement extends HTMLElement {
    __insertReference?: (reference: string) => void;
}

// Global registry for insertReference functions - more reliable than DOM element storage
// Stores a ref wrapper so we can update the function without registry churn
interface InsertReferenceRef {
    fn: (reference: string) => void;
}

// Survive Vite HMR. Without this, every hot reload of this module (or any
// module that imports it, which the field components do) wipes the Map and
// breaks drag-and-drop for fields that haven't re-registered yet — the
// "drop does nothing" symptom after a burst of edits. Dev-only; in prod
// `import.meta.hot` is undefined and we just allocate normally.
const hotData = (import.meta as ImportMeta & { hot?: { data?: Record<string, unknown> } }).hot?.data;
const insertReferenceRegistry: Map<string, InsertReferenceRef> =
    (hotData?.insertReferenceRegistry as Map<string, InsertReferenceRef> | undefined) ??
    new Map<string, InsertReferenceRef>();
if (hotData) {
    hotData.insertReferenceRegistry = insertReferenceRegistry;
}

// Export function to get insertReference for a fieldKey
export const getInsertReferenceForField = (fieldKey: string): ((reference: string) => void) | undefined => {
    const ref = insertReferenceRegistry.get(fieldKey);
    return ref ? (reference: string) => ref.fn(reference) : undefined;
};

// Export registration functions so other droppable components (e.g. SearchableEnumField) can share the registry
export const registerInsertReference = (fieldKey: string, ref: { fn: (reference: string) => void }) => {
    insertReferenceRegistry.set(fieldKey, ref);
};
export const unregisterInsertReference = (fieldKey: string) => {
    insertReferenceRegistry.delete(fieldKey);
};

// Helper to create a reference string from drag data. Emits the `$()` accessor
// form so a dragged value is immediately ready for inline transforms.
export const createReferenceString = (nodeId: string, path: string): string => {
    return `{{ ${pathToExpression(nodeId, path)} }}`;
};

// Helper to check if a value contains any references (brace/string-aware, so JS
// expressions with inner `}` are detected too).
export const containsReferences = (value: string): boolean => {
    return scanBlocks(value).length > 0;
};

// Helper to extract all references/expressions from a value (full `{{...}}` tokens).
export const extractReferences = (value: string): string[] => {
    if (typeof value !== 'string') return [];
    return scanBlocks(value).map((b) => value.slice(b.start, b.end));
};

// Remove every `{{...}}` reference/expression and return the remaining text, trimmed.
// Brace-aware so JS blocks with inner `}` are removed whole rather than truncated.
export const stripReferences = (value: string): string => {
    if (typeof value !== 'string') return '';
    const blocks = scanBlocks(value);
    let out = value;
    for (let k = blocks.length - 1; k >= 0; k -= 1) {
        out = out.slice(0, blocks[k].start) + out.slice(blocks[k].end);
    }
    return out.trim();
};

// Parse a reference string into nodeId and path
// e.g., "{{node1.output.data}}" -> { nodeId: "node1", path: "output.data" }
export const parseReference = (ref: string): { nodeId: string; path: string } | null => {
    const match = ref.match(/\{\{([^.]+)\.(.+)\}\}/);
    if (!match) return null;
    return { nodeId: match[1], path: match[2] };
};

export const DroppableTextField = ({
    value,
    onChange,
    placeholder,
    multiline = false,
    rows = 2,
    autoExpand = true,
    className = '',
    fieldKey,
    hasError = false
}: DroppableTextFieldProps) => {
    // Coerce value to string — backend/AI builder may produce null, boolean, or numeric config values
    value = value == null ? '' : String(value);

    const inputRef = useRef<HTMLInputElement | HTMLTextAreaElement>(null);
    const [cursorPosition, setCursorPosition] = useState<number | null>(null);
    const [isActive, setIsActive] = useState(false);

    // Validation state - track when user is actively editing vs done
    const [isEditing, setIsEditing] = useState(false);
    const editTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    // Reference autocomplete context - may not be available
    const autocompleteContext = useReferenceAutocomplete();
    // Hover/scroll context — used to reveal a clicked reference in the Input panel
    // (null outside the workflow editor).
    const referenceHover = useReferenceHover();

    // Shared parsing + validation. The reference indicator (link/warning icon)
    // still wants the set form to decide its hue.
    const { hasReferences, invalidReferences } = useReferenceSegments(value);

    // Set up droppable
    const { setNodeRef, isOver, active } = useDroppable({
        id: `droppable-field-${fieldKey}`,
        data: {
            type: 'config-field',
            fieldKey,
        },
    });

    // Check if the active draggable is a JSON field reference
    const isJsonFieldDrag = active?.data?.current?.type === 'json-field-reference';

    // Track cursor position for drag-drop / scaffold insertion. Reference building is
    // handled by the always-on ExpressionPanel, not an inline dropdown.
    const handleSelect = useCallback(() => {
        if (inputRef.current) {
            setCursorPosition(inputRef.current.selectionStart ?? 0);
        }
    }, []);

    // On click, also reveal the reference under the caret in the Input panel (scrolls
    // + briefly highlights the matching field). Click now lands the caret naturally —
    // this restores the navigate-to-source behavior the chip click used to provide.
    const handleClick = useCallback(() => {
        handleSelect();
        const pos = inputRef.current?.selectionStart;
        if (pos == null || !referenceHover) return;
        const ref = referenceAtCursor(value, pos);
        if (ref) referenceHover.setScrollToReference(ref);
    }, [handleSelect, referenceHover, value]);

    const handleChange = useCallback((e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
        const newValue = e.target.value;
        const newCursorPos = e.target.selectionStart ?? 0;

        // Mark as editing and reset the timeout
        setIsEditing(true);
        if (editTimeoutRef.current) {
            clearTimeout(editTimeoutRef.current);
        }
        // After 1.5s of no typing, mark as done editing (for validation display)
        editTimeoutRef.current = setTimeout(() => {
            setIsEditing(false);
        }, 1500);

        // Auto-scaffold: completing a fresh `{{` expands it to `{{ $('') }}` with the
        // cursor inside the quotes. The ExpressionPanel below then shows the picker. Only
        // on INSERTION (newValue grew) so backspacing through `{{` doesn't re-scaffold.
        if (
            autocompleteContext &&
            newValue.length > value.length &&
            newCursorPos >= 2 &&
            newValue.slice(newCursorPos - 2, newCursorPos) === '{{' &&
            newValue[newCursorPos - 3] !== '{' &&
            !/^\s*\$\(/.test(newValue.slice(newCursorPos))
        ) {
            const after = newValue.slice(newCursorPos);
            const scaffold = /^\s*\}\}/.test(after) ? " $('')" : " $('') }}";
            const scaffolded = newValue.slice(0, newCursorPos) + scaffold + after;
            const cursorInQuotes = newCursorPos + 4; // just past " $('"
            onChange(scaffolded);
            setCursorPosition(cursorInQuotes);
            setTimeout(() => {
                if (inputRef.current) {
                    inputRef.current.focus();
                    inputRef.current.setSelectionRange(cursorInQuotes, cursorInQuotes);
                }
            }, 0);
            return;
        }

        onChange(newValue);
        setCursorPosition(newCursorPos);
    }, [onChange, autocompleteContext, value]);

    // Insert a reference at the current cursor position
    const insertReference = useCallback((reference: string) => {
        const pos = cursorPosition ?? value.length;
        const newValue = value.slice(0, pos) + reference + value.slice(pos);
        onChange(newValue);

        // Update cursor position after insertion
        const newPos = pos + reference.length;
        setCursorPosition(newPos);

        // Focus and set cursor position
        setTimeout(() => {
            if (inputRef.current) {
                inputRef.current.focus();
                inputRef.current.setSelectionRange(newPos, newPos);
            }
        }, 0);
    }, [cursorPosition, value, onChange]);

    // Use a ref to hold the insertReference function wrapper
    // This allows us to update the function without removing/re-adding to the registry
    const insertRefWrapper = useRef<InsertReferenceRef | null>(null);

    // Register in global registry on mount, update function on every render
    useEffect(() => {
        // Create the ref wrapper if it doesn't exist
        if (!insertRefWrapper.current) {
            insertRefWrapper.current = { fn: insertReference };
            insertReferenceRegistry.set(fieldKey, insertRefWrapper.current);
        } else {
            // Update the function in the existing wrapper
            insertRefWrapper.current.fn = insertReference;
        }

        // Also store on DOM element as backup
        if (inputRef.current) {
            (inputRef.current as ExtendedHTMLElement).__insertReference = insertReference;
        }

        return () => {
            // Only clean up on unmount (when fieldKey changes or component unmounts)
            insertReferenceRegistry.delete(fieldKey);
            insertRefWrapper.current = null;
        };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- registry mount is keyed only by fieldKey; sibling effect refreshes fn.
    }, [fieldKey]);

    // Keep the function in the wrapper up to date
    useEffect(() => {
        if (insertRefWrapper.current) {
            insertRefWrapper.current.fn = insertReference;
        }
        if (inputRef.current) {
            (inputRef.current as ExtendedHTMLElement).__insertReference = insertReference;
        }
    }, [insertReference]);

    // Cleanup timeout on unmount
    useEffect(() => {
        return () => {
            if (editTimeoutRef.current) {
                clearTimeout(editTimeoutRef.current);
            }
        };
    }, []);

    // No JS height adjustment needed — CSS field-sizing: content handles auto-expand natively
    // Set initial container height from content (capped at 500px) so resize-y works freely
    const scrollContainerRef = useRef<HTMLDivElement>(null);
    const initialHeightSet = useRef(false);
    useEffect(() => {
        if (!multiline || !autoExpand || !scrollContainerRef.current) return;
        // Only set initial height once, then let the user resize freely
        if (initialHeightSet.current) return;
        initialHeightSet.current = true;
        const container = scrollContainerRef.current;
        // Use scrollHeight (full content) capped at 500px
        const contentHeight = container.scrollHeight;
        if (contentHeight > 500) {
            container.style.height = '500px';
        }
    }, [multiline, autoExpand]);

    // Common input classes
    // When multiline+autoExpand, border/bg/rounded move to the parent scroll container
    const isScrollContainer = multiline && autoExpand;
    const [dragStableHeight, setDragStableHeight] = useState<number | null>(null);
    useLayoutEffect(() => {
        if (!isScrollContainer || !isJsonFieldDrag) {
            setDragStableHeight(null);
            return;
        }
        const stableTarget = scrollContainerRef.current ?? inputRef.current;
        const height = stableTarget?.getBoundingClientRect().height;
        setDragStableHeight(height ? Math.ceil(height) : null);
    }, [isJsonFieldDrag, isScrollContainer]);

    const baseClasses = isScrollContainer
        ? "w-full px-3 py-2 text-sm bg-transparent text-foreground/80 placeholder:text-[hsl(var(--placeholder))] focus:outline-none transition-colors"
        // Light: white fill so the field reads as an input on the off-white panel.
        // Dark: keep the subtle foreground/[0.02] raise.
        : "w-full px-3 py-2 text-sm bg-card dark:bg-foreground/[0.02] border rounded-lg text-foreground/80 placeholder:text-[hsl(var(--placeholder))] focus:outline-none transition-colors";

    // Visual feedback classes based on drop state and error state
    // Error state takes precedence over drop state
    // Bg overrides carry a dark: variant so they still beat the base's
    // dark:bg-foreground/[0.02] in dark mode (cn/twMerge resolves last-wins).
    const dropStateClasses = hasError
        ? 'border-red-500/50 focus:border-red-500/70 bg-red-500/5 dark:bg-red-500/5'
        : isOver && isJsonFieldDrag
        ? 'border-muted-foreground/60 dark:border-zinc-500/60 bg-foreground/[0.06] dark:bg-foreground/[0.06] ring-2 ring-muted-foreground/20 dark:ring-zinc-500/20'
        : isJsonFieldDrag && isActive
        ? 'border-muted-foreground/40 dark:border-zinc-500/40'
        : 'border-border dark:border-white/[0.05] focus:border-foreground/20';

    // The `hasReferences` flag comes from useReferenceSegments above — we just
    // pre-compute the invalid count locally for the indicator hue.
    const hasInvalidReferences = invalidReferences.size > 0;

    // Remove all references/expressions from the value, keeping the rest.
    const removeReferences = useCallback(() => {
        onChange(stripReferences(value));
    }, [value, onChange]);

    const combinedClasses = isScrollContainer
        ? cn(baseClasses, className)
        : cn(baseClasses, dropStateClasses, className);
    const textareaAutoExpandStyle = autoExpand ? ({
        fieldSizing: 'content',
        ...(dragStableHeight ? { minHeight: `${dragStableHeight}px` } : {}),
    } satisfies CSSProperties & { fieldSizing: string }) : undefined;
    const scrollContainerStyle = isScrollContainer && dragStableHeight
        ? ({ height: `${dragStableHeight}px` } satisfies CSSProperties)
        : undefined;

    // Reference indicator component - shows link icon (or warning if invalid), X on hover to remove
    const ReferenceIndicator = hasReferences ? (
        <button
            type="button"
            onClick={removeReferences}
            // Scroll-container (expandable) fields render this in the OUTER wrapper, which
            // also spans the expression panel — so anchor to the field's first line
            // (`top-2`) rather than the stack's vertical center, which would drop it onto
            // the panel. Single-line inputs stay vertically centered.
            className={`absolute right-3.5 z-10 flex items-center justify-center w-5 h-5 rounded-full transition-all group ${
                isScrollContainer ? 'top-2' : 'top-1/2 -translate-y-1/2'
            } ${
                hasInvalidReferences && !isEditing
                    ? 'text-red-600 dark:text-red-400 hover:text-white hover:bg-red-500/50'
                    : 'text-muted-foreground hover:text-foreground hover:bg-accent dark:hover:bg-zinc-700/50'
            }`}
            title={hasInvalidReferences && !isEditing ? 'Invalid references - click to remove all' : 'Remove references'}
        >
            {hasInvalidReferences && !isEditing ? (
                <>
                    <AlertCircle className="h-3 w-3 group-hover:hidden" />
                    <X className="h-3 w-3 hidden group-hover:block" />
                </>
            ) : (
                <>
                    <Link2 className="h-3 w-3 group-hover:hidden" />
                    <X className="h-3 w-3 hidden group-hover:block" />
                </>
            )}
        </button>
    ) : null;

    // The opaque hint covers the field without changing placeholder/content
    // sizing, which keeps dnd-kit collision geometry stable while hovering.
    const showDropHint = isOver && isJsonFieldDrag;

    // Drop hint overlay - zinc theme with opaque background to hide placeholder
    const DropHint = isJsonFieldDrag ? (
        <div
            className={`absolute inset-0 flex items-center justify-center bg-card/95 rounded-lg pointer-events-none border-2 border-dashed border-muted-foreground/50 dark:border-zinc-500/50 transition-opacity ${showDropHint ? 'opacity-100' : 'opacity-0'}`}
            aria-hidden={!showDropHint}
        >
            <span className="text-xs text-foreground/80 font-medium">Drop to insert</span>
        </div>
    ) : null;

    const ReferenceHoverOverlay = (
        <ReferenceHighlightOverlay
            value={value}
            inputClassName={`px-3 py-2 text-sm ${className}`}
            multiline={multiline}
            isEditing={isEditing}
            extraClassName="pr-8"
            scrollRef={inputRef}
        />
    );

    // For scroll containers, wrap in an outer relative div so the indicator stays fixed
    // Combine droppable ref and scroll container ref
    const setCombinedRef = useCallback((node: HTMLDivElement | null) => {
        setNodeRef(node);
        (scrollContainerRef as React.MutableRefObject<HTMLDivElement | null>).current = node;
    }, [setNodeRef]);

    const scrollContainerInner = (
        <div
            ref={isScrollContainer ? setCombinedRef : setNodeRef}
            className={`relative ${isScrollContainer ? `overflow-y-scroll scrollbar-subtle rounded-lg border bg-card dark:bg-foreground/[0.02] ${isJsonFieldDrag ? 'resize-none' : 'resize-y'} ${dropStateClasses}` : ''}`}
            style={scrollContainerStyle}
            onFocus={() => setIsActive(true)}
            onBlur={() => setIsActive(false)}
        >
            {multiline ? (
                <textarea
                    ref={inputRef as React.RefObject<HTMLTextAreaElement>}
                    value={value}
                    onChange={handleChange}
                    onSelect={handleSelect}
                    onClick={handleClick}
                    placeholder={placeholder}
                    rows={autoExpand ? undefined : rows}
                    className={`${combinedClasses} block resize-none overflow-hidden ${hasReferences ? 'pr-8' : ''}`}
                    style={textareaAutoExpandStyle}
                    data-field-key={fieldKey}
                />
            ) : (
                <input
                    ref={inputRef as React.RefObject<HTMLInputElement>}
                    type="text"
                    value={value}
                    onChange={handleChange}
                    onSelect={handleSelect}
                    onClick={handleClick}
                    placeholder={placeholder}
                    className={`${combinedClasses} block ${hasReferences ? 'pr-8' : ''}`}
                    data-field-key={fieldKey}
                />
            )}
            {ReferenceHoverOverlay}
            {!isScrollContainer && ReferenceIndicator}
            {DropHint}
        </div>
    );

    // The ExpressionPanel is the always-on reference + transformation builder. Shown
    // whenever the cursor sits inside a `{{ $() }}` block (even one embedded in text), so
    // it can guide node → fields → transforms → preview. Hidden when blurred / outside a
    // reference.
    const activeBlock = isActive && autocompleteContext && cursorPosition !== null ? blockAtCursor(value, cursorPosition) : null;
    const expressionPanel = activeBlock
        ? <ExpressionPanel block={activeBlock} value={value} onChange={onChange} />
        : null;

    // The "Add reference" affordance lives in NodeConfig's contextual-button row
    // (alongside "Show previous nodes") so they share one row; it inserts the
    // `{{ $('') }}` scaffold via the insert-reference registry, which opens this panel.

    if (isScrollContainer) {
        return (
            <div className="relative">
                {scrollContainerInner}
                {ReferenceIndicator}
                {/* Outside the scroll container so it isn't clipped by overflow-y-scroll. */}
                {expressionPanel}
            </div>
        );
    }

    if (expressionPanel) {
        return (
            <>
                {scrollContainerInner}
                {expressionPanel}
            </>
        );
    }

    return scrollContainerInner;
};
