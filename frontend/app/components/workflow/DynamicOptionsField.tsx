// DynamicOptionsField - Combobox component for NodeConfig fields with dynamic options loaded from backend.
// Used for fields like spreadsheet selection that need to fetch options via API with user credentials.
// Supports infinite scroll pagination for large datasets and {{reference}} autocomplete.

import { Fragment, useState, useCallback, useRef, useEffect, useMemo } from 'react';
import { Loader2, ChevronDown, Edit3, AlertTriangle, Link2, Variable, X, ArrowUpRight } from 'lucide-react';
import { useDroppable } from '@dnd-kit/core';
import { sendEventAsync } from '~/lib/socket-sender';
import { WorkflowNodeLoadOptionsRequest } from '~/types/socket-events.generated';
import type { WorkflowNodeLoadOptionsResponse, FieldOption } from '~/types/socket-events.generated';
import { useReferenceAutocomplete, type ReferenceSuggestion } from './ReferenceAutocompleteContext';
import {
    containsReferences,
    registerInsertReference,
    unregisterInsertReference,
} from './DroppableTextField';
import { ReferenceHighlightOverlay } from './ReferenceHighlight';
import { valueToText } from './valueText';

// Dynamic options configuration from x-dynamic-options schema metadata
interface DynamicOptionsConfig {
    field_name: string;
    placeholder?: string;
    searchable?: boolean;
    allow_custom?: boolean;
    custom_placeholder?: string;
    depends_on?: string;        // Field that this dropdown depends on (e.g., spreadsheet_id)
    auto_select_first?: boolean; // Take options[0] whatever the length (ordered lists only)
    auto_select_sole_option?: boolean; // Fill only when the complete list holds exactly one
}

function getOptionIcon(option: FieldOption): string | null {
    const icon = option.metadata?.icon;
    return typeof icon === 'string' && icon.length > 0 ? icon : null;
}

function getOptionEmoji(option: FieldOption): string | null {
    const emoji = option.metadata?.emoji;
    return typeof emoji === 'string' && emoji.length > 0 ? emoji : null;
}

function supportsOptionArtwork(nodeType: string): boolean {
    return nodeType === 'automation-google-drive';
}

export interface DynamicOptionsFieldProps {
    fieldKey: string;
    prop: any;
    value: unknown;
    onChange: (key: string, value: string) => void;
    nodeType: string;
    credentialIds: Record<string, string>;
    config: Record<string, any>;
    hasError?: boolean; // Whether this field has execution errors (shows red border)
    onOpenCredentials?: () => void; // Switch to the Credentials tab (shown when no credential is connected)
}

// Detect partial {{reference}} for autocomplete (shared with SearchableEnumField)
function detectPartialReference(val: string, cursorPos: number): { partial: string; startIndex: number } | null {
    const textBeforeCursor = val.slice(0, cursorPos);
    const lastOpenBrace = textBeforeCursor.lastIndexOf('{{');
    if (lastOpenBrace === -1) return null;
    const textAfterBrace = textBeforeCursor.slice(lastOpenBrace + 2);
    if (textAfterBrace.includes('}}')) return null;
    return { partial: textAfterBrace, startIndex: lastOpenBrace };
}

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

// DynamicOptionsField component for fields with x-dynamic-options metadata
// Uses combobox pattern - main input doubles as search field
// Supports infinite scroll pagination - loads more options when scrolling near bottom
export function DynamicOptionsField({
    fieldKey,
    prop,
    value,
    onChange,
    nodeType,
    credentialIds,
    config,
    hasError = false,
    onOpenCredentials
}: DynamicOptionsFieldProps) {
    const [options, setOptions] = useState<FieldOption[]>([]);
    const [loading, setLoading] = useState(false);
    const [loadingMore, setLoadingMore] = useState(false); // Separate state for pagination loading
    const [error, setError] = useState<string | null>(null);
    const [isOpen, setIsOpen] = useState(false);
    const [inputValue, setInputValue] = useState('');
    const [isFocused, setIsFocused] = useState(false);
    const [highlightedIndex, setHighlightedIndex] = useState(-1);
    const [hasAttemptedLoad, setHasAttemptedLoad] = useState(false); // Prevent infinite retries
    const [valueNotFound, setValueNotFound] = useState(false); // True when pre-populated value isn't in options
    const [nextPageToken, setNextPageToken] = useState<string | null>(null); // Pagination token
    const isLoadingRef = useRef(false); // Ref-based guard against concurrent loads
    // Monotonic counter for in-flight loadOptions requests. Stamped onto each
    // call so out-of-order responses (later keystroke fires before earlier
    // request resolves) can be discarded instead of overwriting the latest.
    const latestRequestSeqRef = useRef(0);
    // Tracks the search term whose load was most recently claimed by
    // ``loadOptions`` (set synchronously before the await). The debounce effect
    // dedupes against this so the initial empty load + the open-dropdown
    // effect don't both fire identical "search=''" requests. Initialised to
    // ``null`` so the first claim — for whatever value — always lands.
    const lastRequestedSearchRef = useRef<string | null>(null);
    const containerRef = useRef<HTMLDivElement>(null);
    const inputRef = useRef<HTMLInputElement>(null);
    const scrollContainerRef = useRef<HTMLDivElement>(null);

    // Reference autocomplete state
    const autocompleteContext = useReferenceAutocomplete();
    const [showRefAutocomplete, setShowRefAutocomplete] = useState(false);
    const [refSelectedIndex, setRefSelectedIndex] = useState(0);
    const [partialRef, setPartialRef] = useState<{ partial: string; startIndex: number } | null>(null);
    const [cursorPosition, setCursorPosition] = useState<number | null>(null);

    const dynamicOptions = prop['x-dynamic-options'] as DynamicOptionsConfig;
    const showOptionArtwork = supportsOptionArtwork(nodeType);
    const valueText = valueToText(value);
    const normalizedOptions = useMemo<FieldOption[]>(
        () => options.map((opt) => ({
            ...opt,
            value: valueToText(opt.value),
            label: valueToText(opt.label || opt.value),
        })),
        [options],
    );
    const commonClasses = `w-full px-3 py-2 text-sm bg-card dark:bg-foreground/[0.02] border rounded-lg text-foreground/80 placeholder:text-[hsl(var(--placeholder))] focus:outline-none transition-colors ${
        hasError
            ? 'border-red-500/50 focus:border-red-500/70 bg-red-500/5'
            : 'border-border dark:border-white/[0.05] focus:border-foreground/20'
    }`;

    // Track the dependent field value to detect changes
    const dependsOn = dynamicOptions.depends_on;
    const dependentValue = dependsOn ? config[dependsOn] : null;
    const prevDependentValue = useRef(dependentValue);

    // Check if value is a reference
    const hasRefs = containsReferences(valueText);

    // Reference autocomplete suggestions
    const refSuggestions = useMemo(() => {
        if (!autocompleteContext || !partialRef) return [];
        return autocompleteContext.getSuggestions(partialRef.partial);
    }, [autocompleteContext, partialRef]);

    // Droppable setup for drag-and-drop references
    const { setNodeRef, isOver, active } = useDroppable({
        id: `droppable-dynamic-${fieldKey}`,
        data: { type: 'config-field', fieldKey },
    });
    const isJsonFieldDrag = active?.data?.current?.type === 'json-field-reference';
    const showDropHint = isOver && isJsonFieldDrag;

    // Insert a reference at cursor position (used by drag-and-drop)
    const insertReference = useCallback((reference: string) => {
        const pos = cursorPosition ?? valueText.length;
        const newValue = valueText.slice(0, pos) + reference + valueText.slice(pos);
        onChange(fieldKey, newValue);
        onChange(`${fieldKey}__label`, ''); // Clear label for reference values

        const newPos = pos + reference.length;
        setCursorPosition(newPos);

        setTimeout(() => {
            if (inputRef.current) {
                inputRef.current.focus();
                inputRef.current.setSelectionRange(newPos, newPos);
            }
        }, 0);
    }, [cursorPosition, valueText, onChange, fieldKey]);

    // Insert a reference suggestion (replaces partial {{...}})
    const insertSuggestion = useCallback((suggestion: ReferenceSuggestion) => {
        if (!partialRef) return;

        const beforeRef = valueText.slice(0, partialRef.startIndex);
        const afterCursor = valueText.slice(cursorPosition ?? valueText.length);
        const closingBraceIndex = afterCursor.indexOf('}}');
        const afterReference = closingBraceIndex !== -1 ? afterCursor.slice(closingBraceIndex + 2) : afterCursor;
        const fullRef = `{{${suggestion.reference}}}`;
        const newValue = beforeRef + fullRef + afterReference;

        onChange(fieldKey, newValue);
        onChange(`${fieldKey}__label`, ''); // Clear label for reference values
        setShowRefAutocomplete(false);
        setPartialRef(null);
        setIsOpen(false);
        setIsFocused(false);

        const newPos = partialRef.startIndex + fullRef.length;
        setCursorPosition(newPos);

        setTimeout(() => {
            if (inputRef.current) {
                inputRef.current.focus();
                inputRef.current.setSelectionRange(newPos, newPos);
            }
        }, 0);
    }, [partialRef, cursorPosition, valueText, onChange, fieldKey]);

    // Register insertReference in the shared global registry for drag-and-drop
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

    // Get credential ID - for OAuth nodes, use the appropriate credential type
    const getCredentialId = useCallback(() => {
        const findCredential = (key: string): string | undefined => {
            if (credentialIds[key]) return credentialIds[key];
            const hyphenated = key.replace(/_/g, '-');
            if (credentialIds[hyphenated]) return credentialIds[hyphenated];
            const underscored = key.replace(/-/g, '_');
            if (credentialIds[underscored]) return credentialIds[underscored];
            return undefined;
        };

        const nodePrefix = nodeType.replace('automation-', '').replace(/-/g, '_');

        if (nodePrefix === 'discord') {
            for (const credentialType of ['discord_bot_install', 'discord_bot_token']) {
                const found = findCredential(credentialType);
                if (found) return found;
            }
        }

        const credTypePatterns = [
            `${nodePrefix}_api_key`,
            `${nodePrefix}_bot_token`,
            `${nodePrefix}_pat`,
            `${nodePrefix}`,
            `${nodePrefix}_oauth`,
            'google_sheets_oauth',
            'google_gmail_oauth',
            'google_oauth',
        ];

        for (const pattern of credTypePatterns) {
            const found = findCredential(pattern);
            if (found) return found;
        }

        // Fallback: return first available credential
        const firstCredId = Object.values(credentialIds)[0];
        return firstCredId || '';
    }, [credentialIds, dynamicOptions.field_name, nodeType]);

    // Load options from backend - accepts optional override context for dependent fields.
    // pageToken: when truthy, appends to existing options (infinite scroll pagination).
    // search: when truthy, narrows the result set server-side. Stamped onto the request
    // so the latest in-flight response wins races (debounced typing can fire multiple
    // requests in quick succession).
    const loadOptions = useCallback(async (
        overrideContext?: Record<string, any>,
        pageToken?: string | null,
        search?: string | null,
    ) => {
        // Guard against concurrent loads using ref (effects can race before state flushes)
        if (isLoadingRef.current) {
            console.log(`[DynamicOptionsField] Skipping load for ${fieldKey} - already loading`);
            return;
        }

        // Get credential ID - may be empty for nodes that don't require credentials
        const credentialId = getCredentialId();

        // Use override context if provided (for dependent fields), otherwise use config
        const contextToSend = overrideContext || config;
        const isPagination = !!pageToken;
        const trimmedSearch = (search || '').trim();
        // Claim this search term BEFORE the await so the debounce effect can
        // dedupe — the open-load effect synchronously calls loadOptions() with
        // no search, this claim makes the empty key '' the "latest requested",
        // and the debounce effect's subsequent run-because-hasAttemptedLoad-
        // flipped sees a match and skips firing a redundant identical fetch.
        // Pagination loads keep the prior claim untouched (the search term
        // doesn't change between page 1 and page 2 of the same query).
        if (!isPagination) {
            lastRequestedSearchRef.current = trimmedSearch;
        }
        const requestSeq = ++latestRequestSeqRef.current;

        console.log(`[DynamicOptionsField] loadOptions called for ${fieldKey}, context:`, contextToSend, `pageToken:`, pageToken, `search:`, trimmedSearch);

        isLoadingRef.current = true;
        if (isPagination) {
            setLoadingMore(true);
        } else {
            setLoading(true);
        }
        setError(null);

        try {
            const response = await sendEventAsync(
                WorkflowNodeLoadOptionsRequest.create({
                    request_id: `load-options-${fieldKey}-${Date.now()}`,
                    node_type: nodeType,
                    field_name: dynamicOptions.field_name,
                    credential_id: credentialId,
                    context: contextToSend,
                    page_token: pageToken || undefined,
                    search: trimmedSearch || undefined,
                })
            ) as WorkflowNodeLoadOptionsResponse;

            // Drop stale responses: a newer request superseded this one.
            if (requestSeq !== latestRequestSeqRef.current) {
                console.log(`[DynamicOptionsField] Dropping stale response for ${fieldKey} (seq ${requestSeq} < ${latestRequestSeqRef.current})`);
                return;
            }

            console.log(`[DynamicOptionsField] Response for ${fieldKey}:`, response, `next_page_token:`, response?.next_page_token);
            if (response?.success && response.options) {
                const newOptions = response.options;
                if (isPagination) {
                    // Append new options to existing ones
                    setOptions(prev => [...prev, ...newOptions]);
                } else {
                    // Replace options (initial load OR new search query)
                    setOptions(newOptions);
                }
                // Store next page token for infinite scroll
                setNextPageToken(response.next_page_token ?? null);
            } else {
                setError(response?.message || 'Failed to load options');
            }
        } catch (err) {
            console.error('[DynamicOptionsField] Error loading options:', err);
            setError(err instanceof Error ? err.message : 'Failed to load options');
        } finally {
            isLoadingRef.current = false;
            setLoading(false);
            setLoadingMore(false);
            setHasAttemptedLoad(true); // Mark that we've tried loading
        }
    }, [fieldKey, nodeType, dynamicOptions.field_name, getCredentialId, config]);

    // Reset options and value when dependent field changes
    useEffect(() => {
        if (dependsOn && prevDependentValue.current !== dependentValue) {
            console.log(`[DynamicOptionsField] Effect: dependent value changed for ${fieldKey}`, {
                prev: prevDependentValue.current,
                new: dependentValue
            });
            const hadPreviousValue = prevDependentValue.current !== undefined && prevDependentValue.current !== null;
            prevDependentValue.current = dependentValue;
            // Clear options so they reload with new context
            setOptions([]);
            setError(null);
            setHasAttemptedLoad(false); // Reset so we can try loading with new context
            setValueNotFound(false); // Clear not-found warning for new context
            setNextPageToken(null); // Reset pagination token for new context
            isLoadingRef.current = false; // Reset loading guard for new context
            // Drop the search-claim so the upcoming context-bound load isn't
            // deduped against the prior context's last-requested term.
            lastRequestedSearchRef.current = null;
            // Clear this field's value when dependent field changes (but not on initial mount)
            if (hadPreviousValue) {
                onChange(fieldKey, '');
                onChange(`${fieldKey}__label`, '');
            }
            // Auto-load options if dependent field has a value
            // Pass explicit context with the dependent value to avoid stale closure issues
            if (dependentValue) {
                loadOptions({ ...config, [dependsOn]: dependentValue });
            }
        }
    }, [dependsOn, dependentValue, fieldKey, onChange, loadOptions, config]);

    // Handle scroll for infinite pagination - load more when near bottom.
    // Preserves the active search term so paginated results stay within the
    // current query (without this, "load more" would silently revert to the
    // unfiltered next page).
    const handleScroll = useCallback(() => {
        const container = scrollContainerRef.current;
        if (!container || loadingMore || !nextPageToken) return;

        const { scrollTop, scrollHeight, clientHeight } = container;
        const nearBottom = scrollTop + clientHeight >= scrollHeight - 50; // 50px threshold

        if (nearBottom) {
            console.log(`[DynamicOptionsField] Near bottom, loading more for ${fieldKey}`);
            loadOptions(undefined, nextPageToken, inputValue || undefined);
        }
    }, [fieldKey, loadOptions, loadingMore, nextPageToken, inputValue]);

    // Answer the field when there is only one possible answer.
    //
    // Two separate rules, and the difference matters:
    //   auto_select_first      — takes options[0] whatever the length. Only
    //                            meaningful where the list is ordered and the
    //                            first row is the intended default (sheet tabs).
    //   auto_select_sole_option — fires ONLY on a list of exactly one, and only
    //                            once we know the list is complete. Stamped onto
    //                            every required independent picker in the schema,
    //                            so choosing between one thing never reaches the
    //                            user. `nextPageToken` is the guard: a one-row
    //                            first page of a paginated list is not proof
    //                            there is only one, and picking there would
    //                            silently attach the agent to an arbitrary row.
    const soleOption =
        dynamicOptions.auto_select_sole_option && normalizedOptions.length === 1 && !nextPageToken;
    useEffect(() => {
        const shouldFill =
            (dynamicOptions.auto_select_first && normalizedOptions.length > 0) || soleOption;
        if (shouldFill && !valueText) {
            const firstOption = normalizedOptions[0];
            onChange(fieldKey, firstOption.value);
            if (firstOption.label && firstOption.label !== firstOption.value) {
                onChange(`${fieldKey}__label`, firstOption.label);
            }
        }
    }, [
        normalizedOptions,
        valueText,
        dynamicOptions.auto_select_first,
        soleOption,
        fieldKey,
        onChange,
    ]);

    // Auto-resolve label when options load and we have a pre-populated value
    // This converts IDs (like spreadsheet_id) to human-readable names
    // Also detects when a pre-populated value isn't found (e.g., wrong account)
    useEffect(() => {
        if (normalizedOptions.length === 0 || !valueText) {
            setValueNotFound(false);
            return;
        }
        // Don't try to resolve labels for reference values
        if (containsReferences(valueText)) {
            setValueNotFound(false);
            return;
        }
        // Skip label resolution if we already have a stored label
        const storedLabel = config[`${fieldKey}__label`];

        // Find matching option
        const matchingOption = normalizedOptions.find(opt => opt.value === valueText);

        if (matchingOption) {
            // Value found in options - clear any not-found warning
            setValueNotFound(false);
            // Sync the stored label. Overwrites a stale sidecar left behind
            // by an external writer that updated `value` without touching
            // `${fieldKey}__label` (e.g. the agent node's on-canvas
            // ModelDropdown writing a new model id).
            if (matchingOption.label && matchingOption.label !== matchingOption.value && matchingOption.label !== storedLabel) {
                console.log(`[DynamicOptionsField] Auto-resolved label for ${fieldKey}: ${matchingOption.label}`);
                onChange(`${fieldKey}__label`, matchingOption.label);
            }
        } else if (!storedLabel) {
            // Value not found in options - warn user (could be wrong account or invalid ID)
            // Show warning even if allow_custom is true, since user should know the ID wasn't found
            console.log(`[DynamicOptionsField] Value not found in options for ${fieldKey}: ${valueText}`);
            setValueNotFound(true);
        }
    }, [normalizedOptions, valueText, fieldKey, config, onChange]);

    // Load options when dropdown opens (and not already loaded/attempted)
    useEffect(() => {
        // Don't load if we depend on a field that has no value
        if (dependsOn && !dependentValue) {
            return;
        }
        // Don't retry if we've already attempted to load (prevents infinite loop on empty results)
        if (isOpen && options.length === 0 && !loading && !error && !hasAttemptedLoad) {
            console.log(`[DynamicOptionsField] Effect: loading on open for ${fieldKey}`, {
                isOpen, optionsLength: options.length, loading, error, hasAttemptedLoad
            });
            loadOptions();
        }
    }, [isOpen, options.length, loading, error, loadOptions, dependsOn, dependentValue, hasAttemptedLoad]);

    // Stable ref to the latest loadOptions so the search-debounce effect below
    // doesn't re-arm every time sibling config fields change (loadOptions's
    // closure captures `config`, so its identity churns on unrelated edits).
    const loadOptionsRef = useRef(loadOptions);
    useEffect(() => { loadOptionsRef.current = loadOptions; }, [loadOptions]);

    // Debounced re-fetch when the user types in the search box. Without this,
    // search is a local substring filter over whatever happened to be on the
    // first page — items that exist server-side but weren't in the loaded set
    // are unreachable. Resets pagination (page_token: null) so a new search
    // starts a fresh result window instead of stacking onto previous pages.
    // Skipped when input holds a {{reference}} template (those are value edits,
    // not searches) or when the dropdown is closed.
    //
    // Dedupe is two-layer to keep the dropdown from visibly double-loading:
    //
    //   (1) Eagerly: skip arming the timer when the input already matches
    //       what was last requested. This catches the common "open dropdown,
    //       initial fetch completes, hasAttemptedLoad flips, effect re-runs
    //       with the same empty input" race.
    //   (2) Lazily: re-check inside the timer right before firing, since
    //       another claim could have landed during the 250ms wait (e.g. a
    //       pagination scroll, or a dependent-field reload).
    useEffect(() => {
        if (!isOpen) return;
        if (dependsOn && !dependentValue) return;
        if (containsReferences(inputValue)) return;
        const desired = (inputValue || '').trim();
        // Eager dedupe: same query as the last claim → no-op.
        if (lastRequestedSearchRef.current === desired) return;
        const handle = setTimeout(() => {
            // Lazy dedupe: state may have caught up while we were waiting.
            if (lastRequestedSearchRef.current === desired) return;
            // pageToken=null is the explicit reset signal to loadOptions: discard
            // any accumulated pages, treat the response as a fresh result set.
            loadOptionsRef.current(undefined, null, desired || undefined);
        }, 250);
        return () => clearTimeout(handle);
    }, [inputValue, isOpen, dependsOn, dependentValue]);

    // Auto-load options when we have a pre-populated value but no stored label
    // This resolves IDs (like spreadsheet_id) to human-readable names automatically
    useEffect(() => {
        // Skip if we depend on a field that has no value
        if (dependsOn && !dependentValue) {
            return;
        }
        // Skip if no value, already have options, already loading, or already attempted
        if (!valueText || options.length > 0 || loading || hasAttemptedLoad) {
            return;
        }
        // Skip for reference values - no need to resolve labels
        if (containsReferences(valueText)) {
            return;
        }
        // Skip if we already have a stored label for this value
        const storedLabel = config[`${fieldKey}__label`];
        if (storedLabel) {
            return;
        }
        // We have a value but no label - load options to resolve the name
        console.log(`[DynamicOptionsField] Effect: auto-loading for pre-populated value ${fieldKey}=${valueText}`);
        loadOptions();
    }, [valueText, options.length, loading, hasAttemptedLoad, fieldKey, config, loadOptions, dependsOn, dependentValue]);

    // Close dropdown when clicking outside
    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
                setIsOpen(false);
                setIsFocused(false);
                setShowRefAutocomplete(false);
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, []);

    // Filter unconditionally on inputValue (handleBlur + click-outside reset
    // it to ''). Gating on isFocused would silently disable filtering when
    // focus state and inputValue desync. Cap the rendered slice — mounting
    // thousands of buttons per keystroke is slow enough that React 18 defers
    // commits and the new render never reaches the DOM.
    const MAX_RENDERED_OPTIONS = 100;
    const { filteredOptions, truncatedCount } = useMemo(() => {
        const q = inputValue.toLowerCase();
        const matches = normalizedOptions.filter(opt =>
            opt.label.toLowerCase().includes(q) ||
            opt.value.toLowerCase().includes(q)
        );
        const sliced = matches.slice(0, MAX_RENDERED_OPTIONS);
        return { filteredOptions: sliced, truncatedCount: matches.length - sliced.length };
    }, [normalizedOptions, inputValue]);

    // Find selected option label for display
    // First check stored label (persists across node selection), then loaded options, then raw value
    const storedLabel = valueToText(config[`${fieldKey}__label`]);
    const selectedOption = normalizedOptions.find(opt => opt.value === valueText);
    const displayValue = storedLabel || selectedOption?.label || valueText || '';

    // Enter search mode: dropdown open, input acting as a search box. Seeds
    // with the raw value for {{reference}} edits, otherwise starts blank (the
    // current selection stays visible as the placeholder).
    const enterSearchMode = useCallback((seed: string) => {
        setIsFocused(true);
        setIsOpen(true);
        setInputValue(seed);
        setCursorPosition(seed.length);
    }, []);

    // Handle input focus
    const handleFocus = () => {
        enterSearchMode(hasRefs ? valueText : '');
    };

    // Selecting an option closes the dropdown without blurring (option buttons
    // preventDefault on mousedown), so onFocus won't refire — reopen on click.
    const handleClick = () => {
        if (!isOpen) enterSearchMode(hasRefs ? valueText : '');
    };

    // Handle input blur - commit custom value if needed
    const handleBlur = () => {
        // Small delay to allow click events on dropdown items to fire first
        setTimeout(() => {
            if (!containerRef.current?.contains(document.activeElement)) {
                setIsFocused(false);
                setShowRefAutocomplete(false);
                // If user typed something that contains references, always commit it
                if (inputValue && containsReferences(inputValue)) {
                    onChange(fieldKey, inputValue);
                    onChange(`${fieldKey}__label`, '');
                } else if (inputValue && dynamicOptions.allow_custom) {
                    const matchingOption = normalizedOptions.find(
                        opt => opt.label.toLowerCase() === inputValue.toLowerCase() ||
                               opt.value.toLowerCase() === inputValue.toLowerCase()
                    );
                    if (matchingOption) {
                        onChange(fieldKey, matchingOption.value);
                        onChange(`${fieldKey}__label`, matchingOption.label);
                    } else {
                        onChange(fieldKey, inputValue);
                        onChange(`${fieldKey}__label`, ''); // Clear label for custom values
                    }
                }
                setInputValue('');
                setIsOpen(false);
            }
        }, 150);
    };

    // Handle input changes — detect {{references}} for autocomplete
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

        // If user typed a complete reference, commit it immediately
        if (containsReferences(newValue)) {
            onChange(fieldKey, newValue);
            onChange(`${fieldKey}__label`, '');
        }

        if (!isOpen) setIsOpen(true);
        if (!isFocused) setIsFocused(true);
    }, [fieldKey, onChange, autocompleteContext, isOpen, isFocused]);

    // Handle option selection - stores both value and label
    const selectOption = useCallback((optValue: string, optLabel?: string) => {
        onChange(fieldKey, optValue);
        // Store label separately so it persists across node selection/deselection
        if (optLabel && optLabel !== optValue) {
            onChange(`${fieldKey}__label`, optLabel);
        } else {
            // Clear stored label if selecting custom value (label === value)
            onChange(`${fieldKey}__label`, '');
        }
        setValueNotFound(false); // Clear warning when user selects an option
        setIsOpen(false);
        setInputValue('');
        setIsFocused(false);
        setShowRefAutocomplete(false);
    }, [fieldKey, onChange]);

    // Handle keyboard navigation — reference autocomplete takes priority
    const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
        // Reference autocomplete navigation
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
                selectOption(highlighted.value, highlighted.label);
            } else if (filteredOptions.length === 1) {
                selectOption(filteredOptions[0].value, filteredOptions[0].label);
            } else if (filteredOptions.length === 0 && inputValue && dynamicOptions.allow_custom) {
                selectOption(inputValue);
            }
        } else if (e.key === 'Escape') {
            // Close without blurring: blur's delayed handler captures the
            // pre-Escape inputValue and would commit the abandoned text on
            // allow_custom fields. Staying focused also lets typing reopen.
            setIsOpen(false);
            setIsFocused(false);
            setInputValue('');
            setShowRefAutocomplete(false);
        }
    }, [showRefAutocomplete, refSuggestions, refSelectedIndex, insertSuggestion, isOpen, enterSearchMode, hasRefs, valueText, filteredOptions, highlightedIndex, inputValue, dynamicOptions.allow_custom, selectOption]);

    // First match pre-highlighted while searching so Enter selects it
    useEffect(() => {
        setHighlightedIndex(inputValue ? 0 : -1);
    }, [inputValue, isOpen]);

    useEffect(() => {
        if (highlightedIndex < 0) return;
        scrollContainerRef.current
            ?.querySelector(`[data-option-index="${highlightedIndex}"]`)
            ?.scrollIntoView({ block: 'nearest' });
    }, [highlightedIndex]);

    return (
        <div className="relative" ref={(el) => { setNodeRef(el); (containerRef as React.MutableRefObject<HTMLDivElement | null>).current = el; }}>
            {/* Combobox Input */}
            <div className="relative">
                <input
                    ref={inputRef}
                    type="text"
                    value={isFocused ? inputValue : displayValue}
                    onChange={handleInputChange}
                    onFocus={handleFocus}
                    onClick={handleClick}
                    onBlur={handleBlur}
                    onKeyDown={handleKeyDown}
                    placeholder={
                        showDropHint
                            ? ''
                            : (isFocused && displayValue)
                                ? displayValue
                                : (
                                    (dynamicOptions.allow_custom && error
                                        ? dynamicOptions.custom_placeholder
                                        : dynamicOptions.placeholder)
                                    || 'Select or type...'
                                )
                    }
                    className={`${commonClasses} pr-10`}
                    data-field-key={fieldKey}
                />
                {/* Highlight `{{ }}` references behind the input text, like a text field. */}
                <ReferenceHighlightOverlay
                    value={isFocused ? inputValue : displayValue}
                    inputClassName="px-3 py-2 text-sm"
                    multiline={false}
                    isEditing={isFocused}
                    extraClassName="pr-10"
                    scrollRef={inputRef}
                />
                <div className="absolute right-3 top-1/2 transform -translate-y-1/2 flex items-center gap-1.5">
                    {loading && <Loader2 className="h-3 w-3 animate-spin text-muted-foreground dark:text-zinc-500 pointer-events-none" />}
                    {hasRefs ? (
                        <button
                            type="button"
                            onClick={() => {
                                onChange(fieldKey, '');
                                onChange(`${fieldKey}__label`, '');
                            }}
                            className="flex items-center justify-center w-5 h-5 rounded-full transition-all group text-muted-foreground hover:text-foreground hover:bg-accent dark:hover:bg-zinc-700/50"
                            title="Remove reference"
                        >
                            <Link2 className="h-3 w-3 group-hover:hidden" />
                            <X className="h-3 w-3 hidden group-hover:block" />
                        </button>
                    ) : (
                        <ChevronDown className={`h-4 w-4 text-muted-foreground dark:text-zinc-500 transition-transform pointer-events-none ${isOpen ? 'rotate-180' : ''}`} />
                    )}
                </div>

                {/* Drop hint overlay */}
                {showDropHint && (
                    <div className="absolute inset-0 flex items-center justify-center bg-card/95 rounded-lg pointer-events-none border-2 border-dashed border-muted-foreground/50 dark:border-zinc-500/50">
                        <span className="text-xs text-foreground/80 font-medium">Drop to insert</span>
                    </div>
                )}
            </div>

            {/* Error when pre-populated value not found in options (only show after successful load) */}
            {valueNotFound && !loading && !error && options.length > 0 && (
                <div className="mt-2 p-2.5 rounded-lg bg-amber-500/10 border border-amber-500/20">
                    <div className="flex items-start gap-2">
                        <AlertTriangle className="h-3.5 w-3.5 text-amber-600 dark:text-amber-400 flex-shrink-0 mt-0.5" />
                        <div className="text-xs text-amber-600 dark:text-amber-400">
                            Value &quot;{valueText}&quot; not found in options. Select a valid option from the dropdown.
                        </div>
                    </div>
                </div>
            )}

            {/* Reference autocomplete dropdown (takes priority over dynamic options) */}
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
                                    index === refSelectedIndex ? 'bg-accent' : 'hover:bg-accent/50'
                                }`}
                            >
                                {suggestion.nodeId === 'vars' ? (
                                    <span className="flex items-center justify-center w-5 h-5 rounded bg-emerald-500/10 dark:bg-green-900/50 text-emerald-600 dark:text-emerald-400">
                                        <Variable size={12} />
                                    </span>
                                ) : (
                                    <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded bg-secondary ${getValueTypeColor(suggestion.valueType)}`}>
                                        {suggestion.valueType}
                                    </span>
                                )}
                                <div className="flex-1 min-w-0">
                                    <div className={`text-xs font-mono truncate ${suggestion.nodeId === 'vars' ? 'text-green-600 dark:text-green-300' : 'text-foreground/80'}`}>
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

            {/* Dynamic options dropdown (when not showing reference autocomplete) */}
            {isOpen && !showRefAutocomplete && (
                <div className="absolute z-50 w-full mt-1 bg-card border border-border dark:border-zinc-700 rounded-lg shadow-2xl overflow-hidden animate-fade-in">
                    <div
                        ref={scrollContainerRef}
                        onScroll={handleScroll}
                        className="max-h-60 overflow-y-auto scrollbar-subtle"
                    >
                        {dependsOn && !dependentValue ? (
                            <div className="px-3 py-4 text-center">
                                <div className="text-xs text-muted-foreground dark:text-zinc-500">
                                    Select a {dependsOn.replace(/_/g, ' ')} first
                                </div>
                            </div>
                        ) : loading ? (
                            <div className="px-3 py-4 text-center">
                                <Loader2 className="h-4 w-4 animate-spin text-muted-foreground dark:text-zinc-500 mx-auto mb-2" />
                                <div className="text-xs text-muted-foreground dark:text-zinc-500">Loading options...</div>
                            </div>
                        ) : error ? (
                            <div className="px-3 py-4">
                                <div className="text-xs text-red-600 dark:text-red-400 mb-2">{error}</div>
                                {dynamicOptions.allow_custom && (
                                    <div className="text-xs text-muted-foreground dark:text-zinc-500 mb-2">
                                        Paste a value manually and press Enter, or click away to keep it.
                                    </div>
                                )}
                                <div className="flex items-center gap-2">
                                    {dynamicOptions.allow_custom && inputValue && (
                                        <button
                                            type="button"
                                            onMouseDown={(e) => e.preventDefault()}
                                            onClick={() => selectOption(inputValue)}
                                            className="inline-flex items-center gap-1 text-xs font-medium text-foreground bg-foreground/[0.06] hover:bg-foreground/[0.1] border border-border dark:border-white/10 rounded-md px-2 py-1 transition-colors"
                                        >
                                            <Edit3 className="h-3 w-3" />
                                            Use "{inputValue}"
                                        </button>
                                    )}
                                    {onOpenCredentials && (
                                        <button
                                            type="button"
                                            onMouseDown={(e) => e.preventDefault()}
                                            onClick={onOpenCredentials}
                                            className="inline-flex items-center gap-1 text-xs font-medium text-foreground bg-foreground/[0.06] hover:bg-foreground/[0.1] border border-border dark:border-white/10 rounded-md px-2 py-1 transition-colors"
                                        >
                                            Open Credentials
                                            <ArrowUpRight className="h-3 w-3" />
                                        </button>
                                    )}
                                    <button
                                        type="button"
                                        onClick={() => loadOptions()}
                                        className="text-xs text-muted-foreground hover:text-foreground underline"
                                    >
                                        Retry
                                    </button>
                                </div>
                            </div>
                        ) : filteredOptions.length > 0 ? (
                            <>
                                {/* Re-key on query so React fully remounts the list;
                                    reusing buttons across queries leaked stale rows
                                    under React 18 + StrictMode. */}
                                <Fragment key={`opts-${inputValue}`}>
                                    {filteredOptions.map((opt, index) => {
                                        const icon = showOptionArtwork ? getOptionIcon(opt) : null;
                                        const emoji = showOptionArtwork ? getOptionEmoji(opt) : null;
                                        return (
                                            <button
                                                key={opt.value}
                                                type="button"
                                                data-option-index={index}
                                                onMouseDown={(e) => e.preventDefault()} // Prevent blur before click
                                                onClick={() => selectOption(opt.value, opt.label)}
                                                onMouseEnter={() => setHighlightedIndex(index)}
                                                className={`w-full px-3 py-2.5 text-sm text-left transition-colors flex items-center justify-between ${
                                                    index === highlightedIndex
                                                        ? 'bg-accent'
                                                        : valueText === opt.value ? 'bg-muted dark:bg-zinc-800/50' : ''
                                                }`}
                                            >
                                                <div className="flex min-w-0 items-center gap-2.5">
                                                    {icon && (
                                                        <img
                                                            src={icon}
                                                            alt=""
                                                            aria-hidden="true"
                                                            className="h-4 w-4 flex-shrink-0"
                                                        />
                                                    )}
                                                    {!icon && emoji && (
                                                        <span
                                                            aria-hidden="true"
                                                            className="w-4 flex-shrink-0 text-center text-sm leading-none"
                                                        >
                                                            {emoji}
                                                        </span>
                                                    )}
                                                    <span className="text-foreground/80 truncate">{opt.label}</span>
                                                </div>
                                                {valueText === opt.value && (
                                                    <div className="h-1.5 w-1.5 rounded-full bg-muted-foreground flex-shrink-0" />
                                                )}
                                            </button>
                                        );
                                    })}
                                </Fragment>
                                {/* Loading indicator for pagination */}
                                {loadingMore && (
                                    <div className="px-3 py-2 text-center border-t border-border">
                                        <Loader2 className="h-3 w-3 animate-spin text-muted-foreground dark:text-zinc-500 mx-auto" />
                                    </div>
                                )}
                                {/* Show hint when more pages available */}
                                {!loadingMore && nextPageToken && (
                                    <div className="px-3 py-1.5 text-center border-t border-border">
                                        <div className="text-[10px] text-muted-foreground/70 dark:text-zinc-600">Scroll for more</div>
                                    </div>
                                )}
                                {/* Show hint when client-side results were capped */}
                                {truncatedCount > 0 && (
                                    <div className="px-3 py-1.5 text-center border-t border-border">
                                        <div className="text-[10px] text-muted-foreground/70 dark:text-zinc-600">
                                            +{truncatedCount} more — type to narrow
                                        </div>
                                    </div>
                                )}
                            </>
                        ) : inputValue && dynamicOptions.allow_custom ? (
                            // No matches but has input - show option to use typed value
                            <button
                                type="button"
                                onMouseDown={(e) => e.preventDefault()}
                                onClick={() => selectOption(inputValue)}
                                className="w-full px-3 py-2.5 text-sm text-left hover:bg-accent transition-colors flex items-center gap-2"
                            >
                                <Edit3 className="h-3 w-3 text-muted-foreground dark:text-zinc-500" />
                                <span className="text-foreground/80">Use "<span className="text-foreground font-medium">{inputValue}</span>"</span>
                            </button>
                        ) : (
                            <div className="px-3 py-3 text-xs text-muted-foreground dark:text-zinc-500 text-center">
                                {inputValue ? 'No matches found' : 'No options available'}
                            </div>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
}
