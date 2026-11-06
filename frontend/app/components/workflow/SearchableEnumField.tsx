/**
 * SearchableEnumField - Searchable dropdown for enum fields with x-enum-searchable: true.
 * Supports drag-and-drop of {{nodeId.path}} references from the Input panel.
 *
 * Provides a filterable combobox interface for enum fields. The trigger is a typable
 * input that also accepts dropped references, combining enum selection with free-form typing.
 */

import { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import { ChevronDown, Link2, Variable, X } from 'lucide-react';
import { useDroppable } from '@dnd-kit/core';
import { useReferenceAutocomplete, type ReferenceSuggestion } from './ReferenceAutocompleteContext';
import {
    containsReferences,
    stripReferences,
    registerInsertReference,
    unregisterInsertReference,
} from './DroppableTextField';
import { ReferenceHighlightOverlay } from './ReferenceHighlight';
import { scoreFields } from '~/utils/fuzzySearch';
import { valueToText } from './valueText';

interface SearchableEnumFieldProps {
    /** Field identifier */
    fieldKey: string;
    /** Current selected value */
    value: unknown;
    /** Enum values (actual values stored in config) */
    enumValues: unknown[];
    /** Enum labels (display names) - if not provided, uses enumValues */
    enumLabels?: unknown[];
    /** Change handler */
    onChange: (key: string, value: string) => void;
    /** Placeholder text */
    placeholder?: string;
}

export function SearchableEnumField({
    fieldKey,
    value,
    enumValues,
    enumLabels,
    onChange,
    placeholder = 'Select or type a value...'
}: SearchableEnumFieldProps) {
    const [isOpen, setIsOpen] = useState(false);
    const [inputValue, setInputValue] = useState('');
    const [highlightedIndex, setHighlightedIndex] = useState(-1);
    const dropdownRef = useRef<HTMLDivElement>(null);
    const inputRef = useRef<HTMLInputElement>(null);
    const containerRef = useRef<HTMLDivElement>(null);
    const [cursorPosition, setCursorPosition] = useState<number | null>(null);

    // Reference autocomplete
    const autocompleteContext = useReferenceAutocomplete();
    const [showRefAutocomplete, setShowRefAutocomplete] = useState(false);
    const [refSelectedIndex, setRefSelectedIndex] = useState(0);
    const [partialRef, setPartialRef] = useState<{ partial: string; startIndex: number } | null>(null);

    const valueText = valueToText(value);

    // Use enumLabels if provided, otherwise use enumValues
    const labels = enumLabels || enumValues;

    // Create options array from enum values and labels
    const options = enumValues.map((val, idx) => ({
        value: valueToText(val),
        label: valueToText(labels[idx] ?? val)
    }));

    // The text shown in the input: when open, show what user is typing; when closed, show selected value's label
    const selectedLabel = options.find(o => o.value === valueText)?.label || valueText || '';
    const displayValue = isOpen ? inputValue : selectedLabel;

    // Filter + rank options by relevance while searching (only when the
    // dropdown is open). Fuzzy-matches label and value so abbreviations and
    // word reordering still surface the right option, best match first.
    const filteredOptions = isOpen && inputValue
        ? options
            .map(opt => ({
                opt,
                score: scoreFields(
                    [
                        { text: opt.label.toLowerCase(), weight: 1, fuzzy: true },
                        { text: opt.value.toLowerCase(), weight: 0.6, fuzzy: true },
                    ],
                    inputValue,
                ),
            }))
            .filter(s => s.score !== null)
            .sort(
                (a, b) =>
                    (b.score as number) - (a.score as number) ||
                    a.opt.label.localeCompare(b.opt.label),
            )
            .map(s => s.opt)
        : options;

    // Reference autocomplete suggestions
    const refSuggestions = useMemo(() => {
        if (!autocompleteContext || !partialRef) return [];
        return autocompleteContext.getSuggestions(partialRef.partial);
    }, [autocompleteContext, partialRef]);

    // Check if value contains references (for icon display)
    const hasRefs = containsReferences(valueText);

    // Droppable setup
    const { setNodeRef, isOver, active } = useDroppable({
        id: `droppable-enum-${fieldKey}`,
        data: { type: 'config-field', fieldKey },
    });
    const isJsonFieldDrag = active?.data?.current?.type === 'json-field-reference';

    // Detect partial reference for autocomplete
    function detectPartialReference(val: string, cursorPos: number): { partial: string; startIndex: number } | null {
        const textBeforeCursor = val.slice(0, cursorPos);
        const lastOpenBrace = textBeforeCursor.lastIndexOf('{{');
        if (lastOpenBrace === -1) return null;
        const textAfterBrace = textBeforeCursor.slice(lastOpenBrace + 2);
        if (textAfterBrace.includes('}}')) return null;
        return { partial: textAfterBrace, startIndex: lastOpenBrace };
    }

    // Insert a reference at cursor position
    const insertReference = useCallback((reference: string) => {
        const pos = cursorPosition ?? valueText.length;
        const newValue = valueText.slice(0, pos) + reference + valueText.slice(pos);
        onChange(fieldKey, newValue);

        const newPos = pos + reference.length;
        setCursorPosition(newPos);

        setTimeout(() => {
            if (inputRef.current) {
                inputRef.current.focus();
                inputRef.current.setSelectionRange(newPos, newPos);
            }
        }, 0);
    }, [cursorPosition, valueText, onChange, fieldKey]);

    // Insert a reference suggestion (replaces partial)
    const insertSuggestion = useCallback((suggestion: ReferenceSuggestion) => {
        if (!partialRef) return;

        const beforeRef = valueText.slice(0, partialRef.startIndex);
        const afterCursor = valueText.slice(cursorPosition ?? valueText.length);
        const closingBraceIndex = afterCursor.indexOf('}}');
        const afterReference = closingBraceIndex !== -1 ? afterCursor.slice(closingBraceIndex + 2) : afterCursor;
        const fullRef = `{{${suggestion.reference}}}`;
        const newValue = beforeRef + fullRef + afterReference;

        onChange(fieldKey, newValue);
        setShowRefAutocomplete(false);
        setPartialRef(null);
        setIsOpen(false);

        const newPos = partialRef.startIndex + fullRef.length;
        setCursorPosition(newPos);

        setTimeout(() => {
            if (inputRef.current) {
                inputRef.current.focus();
                inputRef.current.setSelectionRange(newPos, newPos);
            }
        }, 0);
    }, [partialRef, cursorPosition, valueText, onChange, fieldKey]);

    // Register insertReference in the shared global registry (from DroppableTextField)
    const insertRefWrapper = useRef<{ fn: (reference: string) => void } | null>(null);

    useEffect(() => {
        if (!insertRefWrapper.current) {
            insertRefWrapper.current = { fn: insertReference };
            registerInsertReference(fieldKey, insertRefWrapper.current);
        } else {
            insertRefWrapper.current.fn = insertReference;
        }
        return () => {
            unregisterInsertReference(fieldKey);
            insertRefWrapper.current = null;
        };
    }, [fieldKey]);

    useEffect(() => {
        if (insertRefWrapper.current) {
            insertRefWrapper.current.fn = insertReference;
        }
    }, [insertReference]);

    // Close dropdown when clicking outside
    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
                setIsOpen(false);
                setInputValue('');
                setShowRefAutocomplete(false);
            }
        };

        if (isOpen) {
            document.addEventListener('mousedown', handleClickOutside);
            return () => document.removeEventListener('mousedown', handleClickOutside);
        }
    }, [isOpen]);

    // Handle input changes
    const handleInputChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
        const newValue = e.target.value;
        setInputValue(newValue);

        const newCursorPos = e.target.selectionStart ?? 0;
        setCursorPosition(newCursorPos);

        // Check for partial reference
        const partial = detectPartialReference(newValue, newCursorPos);
        setPartialRef(partial);
        if (partial && autocompleteContext) {
            setShowRefAutocomplete(true);
            setRefSelectedIndex(0);
        } else {
            setShowRefAutocomplete(false);
        }

        // If user typed a value that contains {{ }}, set it directly as the value
        if (containsReferences(newValue)) {
            onChange(fieldKey, newValue);
        }

        if (!isOpen) setIsOpen(true);
    }, [fieldKey, onChange, autocompleteContext, isOpen]);

    // Handle option selection
    const handleSelect = useCallback((selectedValue: string) => {
        onChange(fieldKey, selectedValue);
        setIsOpen(false);
        setInputValue('');
        setShowRefAutocomplete(false);
    }, [fieldKey, onChange]);

    // Enter search mode: dropdown open, input acting as a search box. Seeds
    // with the raw value for {{reference}} edits, otherwise starts blank (the
    // current selection stays visible as the placeholder).
    const enterSearchMode = useCallback((seed: string) => {
        setIsOpen(true);
        setInputValue(seed);
        setCursorPosition(seed.length);
    }, []);

    // Handle focus - open dropdown in search mode
    const handleFocus = useCallback(() => {
        enterSearchMode(hasRefs ? valueText : '');
    }, [enterSearchMode, hasRefs, valueText]);

    // Selecting an option closes the dropdown without blurring (option buttons
    // preventDefault on mousedown), so onFocus won't refire — reopen on click.
    const handleClick = useCallback(() => {
        if (!isOpen) enterSearchMode(hasRefs ? valueText : '');
    }, [isOpen, enterSearchMode, hasRefs, valueText]);

    // Close on real focus loss (e.g. Tab away) — option clicks never blur
    const handleBlur = useCallback(() => {
        setTimeout(() => {
            if (!containerRef.current?.contains(document.activeElement)) {
                setIsOpen(false);
                setInputValue('');
                setShowRefAutocomplete(false);
            }
        }, 150);
    }, []);

    // Handle keyboard
    const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
        // Reference autocomplete takes priority
        if (showRefAutocomplete && refSuggestions.length > 0) {
            switch (e.key) {
                case 'ArrowDown':
                    e.preventDefault();
                    setRefSelectedIndex(prev => (prev + 1) % refSuggestions.length);
                    return;
                case 'ArrowUp':
                    e.preventDefault();
                    setRefSelectedIndex(prev => (prev - 1 + refSuggestions.length) % refSuggestions.length);
                    return;
                case 'Enter':
                case 'Tab':
                    e.preventDefault();
                    insertSuggestion(refSuggestions[refSelectedIndex]);
                    return;
                case 'Escape':
                    e.preventDefault();
                    setShowRefAutocomplete(false);
                    return;
            }
        }

        // Closed but still focused (right after a selection): typing starts a
        // fresh search instead of dead-ending on the displayed label.
        if (!isOpen) {
            if (e.key === 'Backspace' || e.key === 'Delete') {
                e.preventDefault();
                enterSearchMode('');
            } else if (e.key === 'ArrowDown') {
                e.preventDefault();
                enterSearchMode(hasRefs ? valueText : '');
            } else if (e.key === 'Escape') {
                inputRef.current?.blur();
            } else if (e.key.length === 1 && !e.metaKey && !e.ctrlKey) {
                e.preventDefault();
                enterSearchMode(e.key);
            }
            return;
        }

        // Open dropdown navigation
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            setHighlightedIndex(prev => Math.min(prev + 1, filteredOptions.length - 1));
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            setHighlightedIndex(prev => Math.max(prev - 1, 0));
        } else if (e.key === 'Enter') {
            e.preventDefault();
            const highlighted = filteredOptions[highlightedIndex];
            if (highlighted) {
                handleSelect(highlighted.value);
                return;
            }
            // If input matches an option, select it; otherwise set raw value
            const match = filteredOptions.find(o =>
                o.label.toLowerCase() === inputValue.toLowerCase() ||
                o.value.toLowerCase() === inputValue.toLowerCase()
            );
            if (match) {
                handleSelect(match.value);
            } else if (inputValue) {
                // Allow free-form value (for references or custom input)
                onChange(fieldKey, inputValue);
                setIsOpen(false);
                setInputValue('');
            }
        } else if (e.key === 'Escape') {
            setIsOpen(false);
            setInputValue('');
            setShowRefAutocomplete(false);
        }
    }, [showRefAutocomplete, refSuggestions, refSelectedIndex, insertSuggestion, isOpen, enterSearchMode, hasRefs, valueText, filteredOptions, highlightedIndex, inputValue, handleSelect, onChange, fieldKey]);

    // First match pre-highlighted while searching so Enter selects it
    useEffect(() => {
        setHighlightedIndex(inputValue ? 0 : -1);
    }, [inputValue, isOpen]);

    useEffect(() => {
        if (highlightedIndex < 0) return;
        dropdownRef.current
            ?.querySelector(`[data-option-index="${highlightedIndex}"]`)
            ?.scrollIntoView({ block: 'nearest' });
    }, [highlightedIndex]);

    // Common input classes
    const baseClasses = "w-full px-3 py-2 text-sm bg-card dark:bg-foreground/[0.02] border rounded-lg text-foreground/80 placeholder:text-[hsl(var(--placeholder))] focus:outline-none transition-all";
    const dropStateClasses = isOver && isJsonFieldDrag
        ? 'border-muted-foreground/60 dark:border-zinc-500/60 bg-foreground/[0.06] ring-2 ring-muted-foreground/20 dark:ring-zinc-500/20'
        : 'border-border dark:border-white/[0.05] focus:border-border dark:focus:border-white/[0.15]';

    const showDropHint = isOver && isJsonFieldDrag;

    // Value type color for reference autocomplete
    function getValueTypeColor(type: ReferenceSuggestion['valueType']): string {
        switch (type) {
            case 'string': return 'text-emerald-600 dark:text-emerald-400';
            case 'number': return 'text-blue-600 dark:text-blue-400';
            case 'boolean': return 'text-amber-600 dark:text-amber-400';
            case 'object': return 'text-purple-600 dark:text-purple-400';
            case 'array': return 'text-cyan-600 dark:text-cyan-400';
            case 'null': return 'text-muted-foreground dark:text-zinc-500';
            default: return 'text-muted-foreground';
        }
    }

    return (
        <div ref={(el) => { setNodeRef(el); (containerRef as React.MutableRefObject<HTMLDivElement | null>).current = el; }} className="relative">
            {/* Typable input trigger */}
            <div className="relative">
                <input
                    ref={inputRef}
                    type="text"
                    value={displayValue}
                    onChange={handleInputChange}
                    onFocus={handleFocus}
                    onClick={handleClick}
                    onBlur={handleBlur}
                    onKeyDown={handleKeyDown}
                    placeholder={showDropHint ? '' : (isOpen && selectedLabel) ? selectedLabel : placeholder}
                    className={`${baseClasses} ${dropStateClasses} pr-8 ${!displayValue ? 'text-muted-foreground dark:text-zinc-500' : ''}`}
                    data-field-key={fieldKey}
                />
                {/* Highlight `{{ }}` references behind the input text, like a text field. */}
                <ReferenceHighlightOverlay
                    value={displayValue}
                    inputClassName="px-3 py-2 text-sm"
                    multiline={false}
                    isEditing={isOpen}
                    extraClassName="pr-8"
                    scrollRef={inputRef}
                />
                <div className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-0.5">
                    {/* Clear button — only for fields where empty is a valid enum value */}
                    {Boolean(value) && !isOpen && !hasRefs && enumValues.includes('') && (
                        <button
                            type="button"
                            onClick={(e) => {
                                e.stopPropagation();
                                onChange(fieldKey, '');
                                setInputValue('');
                            }}
                            className="p-0.5 rounded hover:bg-foreground/[0.06] transition-colors"
                            tabIndex={-1}
                            title="Clear selection"
                        >
                            <X className="w-3.5 h-3.5 text-muted-foreground dark:text-zinc-500 hover:text-foreground/80" />
                        </button>
                    )}
                    {hasRefs ? (
                        // Link icon doubles as the remove-reference control (X on hover),
                        // matching text + dynamic-dropdown fields. Strips the {{ }} and
                        // keeps any remaining literal (e.g. `{{ ref }} true` -> `true`).
                        <button
                            type="button"
                            onClick={() => {
                                onChange(fieldKey, stripReferences(valueText));
                                setInputValue('');
                                setIsOpen(false);
                            }}
                            className="flex items-center justify-center w-5 h-5 rounded-full transition-all group text-muted-foreground hover:text-foreground hover:bg-accent dark:hover:bg-zinc-700/50"
                            tabIndex={-1}
                            title="Remove reference"
                        >
                            <Link2 className="w-4 h-4 group-hover:hidden" />
                            <X className="w-4 h-4 hidden group-hover:block" />
                        </button>
                    ) : (
                        <button
                            type="button"
                            onClick={() => {
                                if (isOpen) {
                                    setIsOpen(false);
                                    setInputValue('');
                                } else {
                                    // focus() is a no-op if the input kept focus after a
                                    // selection — open explicitly as well
                                    inputRef.current?.focus();
                                    enterSearchMode('');
                                }
                            }}
                            className="p-0.5"
                            tabIndex={-1}
                        >
                            <ChevronDown className={`w-4 h-4 text-muted-foreground dark:text-zinc-500 transition-transform ${isOpen ? 'rotate-180' : ''}`} />
                        </button>
                    )}
                </div>

                {/* Drop hint overlay */}
                {showDropHint && (
                    <div className="absolute inset-0 flex items-center justify-center bg-card/95 rounded-lg pointer-events-none border-2 border-dashed border-muted-foreground/50 dark:border-zinc-500/50">
                        <span className="text-xs text-foreground/80 font-medium">Drop to insert</span>
                    </div>
                )}
            </div>

            {/* Reference autocomplete dropdown */}
            {showRefAutocomplete && refSuggestions.length > 0 && (
                <div className="absolute z-50 w-full mt-1 bg-card border border-border dark:border-zinc-700 rounded-lg shadow-2xl overflow-hidden animate-fade-in">
                    <div className="max-h-48 overflow-y-auto scrollbar-subtle">
                        {refSuggestions.map((suggestion, index) => (
                            <button
                                key={suggestion.reference}
                                type="button"
                                data-index={index}
                                onMouseDown={(e) => e.preventDefault()}
                                onClick={() => insertSuggestion(suggestion)}
                                onMouseEnter={() => setRefSelectedIndex(index)}
                                className={`w-full px-3 py-2 text-left transition-colors flex items-center gap-2 ${
                                    index === refSelectedIndex ? 'bg-secondary' : 'hover:bg-accent dark:hover:bg-zinc-800/50'
                                }`}
                            >
                                {suggestion.nodeId === 'vars' ? (
                                    <span className="flex items-center justify-center w-5 h-5 rounded bg-green-900/50 text-emerald-600 dark:text-emerald-400">
                                        <Variable size={12} />
                                    </span>
                                ) : (
                                    <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded bg-secondary ${getValueTypeColor(suggestion.valueType)}`}>
                                        {suggestion.valueType}
                                    </span>
                                )}
                                <div className="flex-1 min-w-0">
                                    <div className={`text-xs font-mono truncate ${suggestion.nodeId === 'vars' ? 'text-green-700 dark:text-green-300' : 'text-foreground/80'}`}>
                                        {suggestion.reference}
                                    </div>
                                </div>
                            </button>
                        ))}
                    </div>
                    <div className="px-3 py-1.5 border-t border-border text-[10px] text-muted-foreground/70 dark:text-zinc-600 flex items-center gap-3">
                        <span><kbd className="px-1 py-0.5 bg-secondary rounded">↑↓</kbd> navigate</span>
                        <span><kbd className="px-1 py-0.5 bg-secondary rounded">Tab</kbd> select</span>
                        <span><kbd className="px-1 py-0.5 bg-secondary rounded">Esc</kbd> close</span>
                    </div>
                </div>
            )}

            {/* Enum dropdown (when not showing reference autocomplete) */}
            {isOpen && !showRefAutocomplete && (
                <div ref={dropdownRef} className="absolute z-50 w-full mt-1 bg-card border border-border dark:border-zinc-700 rounded-lg shadow-2xl overflow-hidden animate-fade-in">
                    {/* Options List */}
                    <div className="max-h-60 overflow-y-auto">
                        {filteredOptions.length > 0 ? (
                            filteredOptions.map((option, index) => (
                                <button
                                    key={option.value}
                                    type="button"
                                    data-option-index={index}
                                    onMouseDown={(e) => e.preventDefault()}
                                    onClick={() => handleSelect(option.value)}
                                    onMouseEnter={() => setHighlightedIndex(index)}
                                    className={`w-full px-3 py-2.5 text-sm text-left transition-colors flex items-center justify-between ${
                                        index === highlightedIndex
                                            ? 'bg-secondary text-foreground'
                                            : option.value === valueText
                                                ? 'bg-muted/50 text-foreground'
                                                : 'text-foreground/80'
                                    }`}
                                >
                                    <span className="truncate">{option.label}</span>
                                    {option.value === valueText && (
                                        <span className="text-xs text-emerald-600 dark:text-emerald-400 ml-2">✓</span>
                                    )}
                                </button>
                            ))
                        ) : (
                            <div className="px-3 py-6 text-center text-sm text-muted-foreground dark:text-zinc-500">
                                {inputValue ? `No matches for "${inputValue}"` : 'No options available'}
                            </div>
                        )}
                    </div>

                    {/* Results count footer (when filtering) */}
                    {inputValue && filteredOptions.length > 0 && filteredOptions.length < options.length && (
                        <div className="px-3 py-1.5 bg-muted/30 border-t border-border/50 dark:border-zinc-700/50">
                            <div className="text-[10px] text-muted-foreground dark:text-zinc-500 text-center">
                                {filteredOptions.length} of {options.length} options
                            </div>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}
