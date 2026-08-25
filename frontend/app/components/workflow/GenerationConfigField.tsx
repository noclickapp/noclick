/**
 * GenerationConfigField - Config field component for workflow generation flow.
 * Handles both dynamic options fields (with x-dynamic-options) and simple text fields.
 * Uses React portal for dropdown to prevent clipping by parent containers.
 */

import { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import { createPortal } from 'react-dom';
import { Loader2, ChevronDown, AlertCircle, Edit3 } from 'lucide-react';
import { sendEventAsync } from '~/lib/socket-sender';
import { WorkflowNodeLoadOptionsRequest } from '~/types/socket-events.generated';
import type { WorkflowNodeLoadOptionsResponse, FieldOption } from '~/types/socket-events.generated';
import { cn } from '~/lib/utils';
import type { InputRequest } from './workflowGeneratorMock';
import { valueToText } from './valueText';

// ============================================================================
// Types
// ============================================================================

interface GenerationConfigFieldProps {
    /** The input request containing config field info */
    input: InputRequest;
    /** Called when a value is selected */
    onValueChange: (value: string) => void;
    /** Currently selected value */
    selectedValue?: unknown;
    /** Credential IDs available (mapped by credential type) */
    credentialIds: Record<string, string>;
    /** Config values from other inputs (for dependent fields) */
    configContext: Record<string, any>;
}

// Dynamic options configuration from x-dynamic-options schema metadata
interface DynamicOptionsConfig {
    field_name: string;
    placeholder?: string;
    searchable?: boolean;
    allow_custom?: boolean;
    custom_placeholder?: string;
    depends_on?: string;
    auto_select_first?: boolean;
    auto_select_sole_option?: boolean;
}

// ============================================================================
// Simple Text Input Component (for fields without x-dynamic-options)
// ============================================================================

function SimpleTextInput({
    input,
    onValueChange,
    selectedValue,
}: {
    input: InputRequest;
    onValueChange: (value: string) => void;
    selectedValue?: unknown;
}) {
    const fieldSchema = input.fieldSchema || {};
    const placeholder = fieldSchema.placeholder || `Enter ${input.label?.toLowerCase() || 'value'}...`;

    return (
        <input
            type="text"
            value={valueToText(selectedValue)}
            onChange={(e) => onValueChange(e.target.value)}
            placeholder={placeholder}
            className={cn(
                "w-full px-3 py-2 text-sm rounded-lg border text-left transition-all",
                "bg-foreground/[0.03] border-border dark:border-white/[0.08] text-foreground/80 placeholder:text-[hsl(var(--placeholder))]",
                "focus:outline-none focus:border-muted-foreground/40 dark:focus:border-white/20 focus:bg-foreground/[0.05]"
            )}
        />
    );
}

// ============================================================================
// Dynamic Options Dropdown Component (for fields with x-dynamic-options)
// ============================================================================

function DynamicOptionsDropdown({
    input,
    onValueChange,
    selectedValue,
    credentialIds,
    configContext,
}: GenerationConfigFieldProps) {
    const [options, setOptions] = useState<FieldOption[]>([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [isOpen, setIsOpen] = useState(false);
    const [inputValue, setInputValue] = useState('');
    const [isFocused, setIsFocused] = useState(false);
    const [hasAttemptedLoad, setHasAttemptedLoad] = useState(false);
    const [dropdownPosition, setDropdownPosition] = useState({ top: 0, left: 0, width: 0 });
    const isLoadingRef = useRef(false);
    const containerRef = useRef<HTMLDivElement>(null);
    const inputRef = useRef<HTMLInputElement>(null);

    // Extract config from input
    const nodeType = input.nodeType || '';
    const fieldKey = input.fieldKey || '';
    const fieldSchema = input.fieldSchema || {};
    const dynamicOptions = (fieldSchema['x-dynamic-options'] as DynamicOptionsConfig) || { field_name: fieldKey };
    const selectedValueText = valueToText(selectedValue);
    const normalizedOptions = useMemo<FieldOption[]>(
        () => options.map((opt) => ({
            ...opt,
            value: valueToText(opt.value),
            label: valueToText(opt.label || opt.value),
        })),
        [options],
    );
    const dependsOn = input.dependsOn || dynamicOptions.depends_on;

    // Get dependent value from config context
    const dependentValue = dependsOn ? configContext[dependsOn] : null;
    const prevDependentValue = useRef(dependentValue);

    // Track previous credentialIds to detect changes
    const prevCredentialIdsRef = useRef(credentialIds);

    // Reset error state when credentials change (user might have connected a credential)
    useEffect(() => {
        const prevKeys = Object.keys(prevCredentialIdsRef.current).sort().join(',');
        const currKeys = Object.keys(credentialIds).sort().join(',');
        if (prevKeys !== currKeys) {
            console.log('[GenerationConfigField] Credentials changed, resetting state for', fieldKey);
            setError(null);
            setHasAttemptedLoad(false);
            isLoadingRef.current = false;
            prevCredentialIdsRef.current = credentialIds;
        }
    }, [credentialIds, fieldKey]);

    // Get the credential ID to use for loading options
    const getCredentialId = useCallback((): string => {
        console.log('[GenerationConfigField] getCredentialId called', {
            fieldKey,
            nodeType,
            credentialIds,
            requiredCredentialTypes: input.requiredCredentialTypes,
        });

        const findCredential = (key: string): string | undefined => {
            if (credentialIds[key]) return credentialIds[key];
            const hyphenated = key.replace(/_/g, '-');
            if (credentialIds[hyphenated]) return credentialIds[hyphenated];
            const underscored = key.replace(/-/g, '_');
            if (credentialIds[underscored]) return credentialIds[underscored];
            return undefined;
        };

        if (input.requiredCredentialTypes && input.requiredCredentialTypes.length > 0) {
            for (const credType of input.requiredCredentialTypes) {
                const found = findCredential(credType);
                if (found) {
                    console.log('[GenerationConfigField] Found via requiredCredentialTypes:', credType, found);
                    return found;
                }
            }
        }

        const nodePrefix = nodeType.replace('automation-', '').replace(/-/g, '_');
        const patterns = [
            `${nodePrefix}_oauth`,
            `${nodePrefix}`,
            `google_sheets_oauth`,
            `google_oauth`,
            'google',
        ];

        for (const pattern of patterns) {
            const found = findCredential(pattern);
            if (found) {
                console.log('[GenerationConfigField] Found via pattern:', pattern, found);
                return found;
            }
        }

        const firstCred = Object.values(credentialIds)[0];
        console.log('[GenerationConfigField] Falling back to first credential:', firstCred);
        return firstCred || '';
    }, [credentialIds, nodeType, input.requiredCredentialTypes, fieldKey]);

    // Load options from backend
    const loadOptions = useCallback(async (overrideContext?: Record<string, any>) => {
        if (isLoadingRef.current) return;

        const credentialId = getCredentialId();
        if (!credentialId) {
            setError('Please connect a credential first');
            return;
        }

        const contextToSend = overrideContext || configContext;

        isLoadingRef.current = true;
        setLoading(true);
        setError(null);

        try {
            const response = await sendEventAsync(
                WorkflowNodeLoadOptionsRequest.create({
                    request_id: `gen-load-options-${fieldKey}-${Date.now()}`,
                    node_type: nodeType,
                    field_name: dynamicOptions.field_name || fieldKey,
                    credential_id: credentialId,
                    context: contextToSend,
                })
            ) as WorkflowNodeLoadOptionsResponse;

            if (response?.success && response.options) {
                setOptions(response.options);
            } else {
                setError(response?.message || 'Failed to load options');
            }
        } catch (err) {
            console.error('[GenerationConfigField] Error loading options:', err);
            setError(err instanceof Error ? err.message : 'Failed to load options');
        } finally {
            isLoadingRef.current = false;
            setLoading(false);
            setHasAttemptedLoad(true);
        }
    }, [fieldKey, nodeType, dynamicOptions.field_name, getCredentialId, configContext]);

    // Reset options when dependent field changes
    useEffect(() => {
        if (dependsOn && prevDependentValue.current !== dependentValue) {
            prevDependentValue.current = dependentValue;
            setOptions([]);
            setError(null);
            setHasAttemptedLoad(false);
            isLoadingRef.current = false;

            if (selectedValue) {
                onValueChange('');
            }

            if (dependentValue) {
                loadOptions({ ...configContext, [dependsOn]: dependentValue });
            }
        }
    }, [dependsOn, dependentValue, selectedValue, onValueChange, loadOptions, configContext]);

    // Load options when dropdown opens
    useEffect(() => {
        if (dependsOn && !dependentValue) return;

        if (isOpen && options.length === 0 && !loading && !error && !hasAttemptedLoad) {
            loadOptions();
        }
    }, [isOpen, options.length, loading, error, loadOptions, dependsOn, dependentValue, hasAttemptedLoad]);

    // Auto-load options on mount for DEPENDENT fields when parent value is already set
    // This handles the case where sheet_name field mounts after spreadsheet_id is already selected
    // Non-dependent fields (like spreadsheet_id) load on dropdown open instead
    useEffect(() => {
        // Only auto-load for dependent fields
        if (!dependsOn) return;
        // Skip if dependent value not set yet
        if (!dependentValue) return;
        // Skip if already loaded, loading, or had an error
        if (options.length > 0 || loading || error || hasAttemptedLoad) return;
        // Auto-load on mount
        loadOptions();
    }, [dependsOn, dependentValue, options.length, loading, error, hasAttemptedLoad, loadOptions]);

    // Auto-select first option when options load and auto_select_first is true
    // This is commonly used for dependent fields (e.g., sheet_name auto-selects after spreadsheet loads)
    useEffect(() => {
        const sole =
            dynamicOptions.auto_select_sole_option && normalizedOptions.length === 1;
        if ((dynamicOptions.auto_select_first || sole) && normalizedOptions.length > 0 && !selectedValueText) {
            const firstOption = normalizedOptions[0];
            onValueChange(firstOption.value);
        }
    }, [normalizedOptions, selectedValueText, dynamicOptions.auto_select_first, onValueChange]);

    // Update dropdown position when opening
    useEffect(() => {
        if (isOpen && containerRef.current) {
            const rect = containerRef.current.getBoundingClientRect();
            setDropdownPosition({
                top: rect.bottom + window.scrollY + 4,
                left: rect.left + window.scrollX,
                width: rect.width,
            });
        }
    }, [isOpen]);

    // Close dropdown when any scrollable ancestor scrolls
    useEffect(() => {
        if (!isOpen) return;

        const handleScroll = () => {
            setIsOpen(false);
            setIsFocused(false);
            setInputValue('');
            inputRef.current?.blur();
        };

        // Find all scrollable ancestors and attach listeners
        const scrollableAncestors: Element[] = [];
        let element = containerRef.current?.parentElement;
        while (element) {
            const style = getComputedStyle(element);
            if (
                style.overflow === 'auto' || style.overflow === 'scroll' ||
                style.overflowY === 'auto' || style.overflowY === 'scroll'
            ) {
                scrollableAncestors.push(element);
                element.addEventListener('scroll', handleScroll, { passive: true });
            }
            element = element.parentElement;
        }

        // Also listen to window scroll
        window.addEventListener('scroll', handleScroll, { passive: true });

        return () => {
            scrollableAncestors.forEach(el => el.removeEventListener('scroll', handleScroll));
            window.removeEventListener('scroll', handleScroll);
        };
    }, [isOpen]);

    // Close dropdown when clicking outside
    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            const target = event.target as Node;
            const dropdownEl = document.getElementById(`config-dropdown-${input.id}`);
            if (
                containerRef.current &&
                !containerRef.current.contains(target) &&
                (!dropdownEl || !dropdownEl.contains(target))
            ) {
                setIsOpen(false);
                setIsFocused(false);
                setInputValue('');
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, [input.id]);

    // Filter options based on search input
    const searchQuery = isFocused ? inputValue : '';
    const filteredOptions = useMemo(() =>
        normalizedOptions.filter(opt =>
            opt.label.toLowerCase().includes(searchQuery.toLowerCase()) ||
            opt.value.toLowerCase().includes(searchQuery.toLowerCase())
        ),
    [normalizedOptions, searchQuery]);

    // Find selected option label for display
    const selectedOption = normalizedOptions.find(opt => opt.value === selectedValueText);
    const displayValue = selectedOption?.label || selectedValueText || '';

    // Handlers
    const handleFocus = () => {
        setIsFocused(true);
        setIsOpen(true);
        setInputValue('');
    };

    const handleBlur = () => {
        setTimeout(() => {
            const dropdownEl = document.getElementById(`config-dropdown-${input.id}`);
            if (
                !containerRef.current?.contains(document.activeElement) &&
                (!dropdownEl || !dropdownEl.contains(document.activeElement))
            ) {
                setIsFocused(false);
                if (inputValue && dynamicOptions.allow_custom) {
                    const match = normalizedOptions.find(
                        opt => opt.label.toLowerCase() === inputValue.toLowerCase() ||
                               opt.value.toLowerCase() === inputValue.toLowerCase()
                    );
                    onValueChange(match?.value || inputValue);
                }
                setInputValue('');
                setIsOpen(false);
            }
        }, 150);
    };

    const handleKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            if (filteredOptions.length === 1) {
                onValueChange(filteredOptions[0].value);
                setIsOpen(false);
                setInputValue('');
                inputRef.current?.blur();
            } else if (filteredOptions.length === 0 && inputValue && dynamicOptions.allow_custom) {
                onValueChange(inputValue);
                setIsOpen(false);
                setInputValue('');
                inputRef.current?.blur();
            }
        } else if (e.key === 'Escape') {
            setIsOpen(false);
            setInputValue('');
            inputRef.current?.blur();
        }
    };

    const selectOption = (optValue: string) => {
        onValueChange(optValue);
        setIsOpen(false);
        setInputValue('');
        setIsFocused(false);
    };

    // Check conditions
    const credentialId = getCredentialId();
    const missingCredential = !credentialId;
    const missingDependency = !!(dependsOn && !dependentValue);

    return (
        <div className="relative" ref={containerRef}>
            {/* Input field */}
            <div className="relative">
                <input
                    ref={inputRef}
                    type="text"
                    value={isFocused ? inputValue : displayValue}
                    onChange={(e) => setInputValue(e.target.value)}
                    onFocus={handleFocus}
                    onBlur={handleBlur}
                    onKeyDown={handleKeyDown}
                    placeholder={
                        missingCredential ? 'Connect credential first...' :
                        missingDependency ? `Select ${dependsOn?.replace(/_/g, ' ')} first...` :
                        dynamicOptions.placeholder || 'Select or type...'
                    }
                    disabled={missingCredential || missingDependency}
                    className={cn(
                        "w-full px-3 py-2 text-sm rounded-lg border text-left transition-all pr-10",
                        "bg-foreground/[0.03] border-border dark:border-white/[0.08] text-foreground/80 placeholder:text-[hsl(var(--placeholder))]",
                        "focus:outline-none focus:border-muted-foreground/40 dark:focus:border-white/20 focus:bg-foreground/[0.05]",
                        (missingCredential || missingDependency) && "opacity-60 cursor-not-allowed"
                    )}
                />
                <div className="absolute right-3 top-1/2 transform -translate-y-1/2 flex items-center gap-1.5 pointer-events-none">
                    {loading && <Loader2 className="h-3 w-3 animate-spin text-muted-foreground dark:text-zinc-500" />}
                    <ChevronDown className={cn(
                        "h-4 w-4 text-muted-foreground dark:text-zinc-500 transition-transform",
                        isOpen && "rotate-180"
                    )} />
                </div>
            </div>

            {/* Error message */}
            {error && !missingCredential && !missingDependency && (
                <div className="mt-2 flex items-center gap-1.5 text-xs text-red-600 dark:text-red-400">
                    <AlertCircle className="w-3 h-3" />
                    <span>{error}</span>
                </div>
            )}

            {/* Dropdown rendered via portal */}
            {isOpen && !missingCredential && !missingDependency && createPortal(
                <div
                    id={`config-dropdown-${input.id}`}
                    className="fixed bg-card border border-border rounded-lg shadow-2xl overflow-hidden"
                    style={{
                        top: dropdownPosition.top,
                        left: dropdownPosition.left,
                        width: dropdownPosition.width,
                        zIndex: 9999,
                    }}
                >
                    <div className="max-h-48 overflow-y-auto scrollbar-subtle">
                        {loading ? (
                            <div className="px-3 py-4 text-center">
                                <Loader2 className="h-4 w-4 animate-spin text-muted-foreground dark:text-zinc-500 mx-auto mb-2" />
                                <div className="text-xs text-muted-foreground dark:text-zinc-500">Loading options...</div>
                            </div>
                        ) : filteredOptions.length > 0 ? (
                            filteredOptions.map((opt) => (
                                <button
                                    key={opt.value}
                                    type="button"
                                    onMouseDown={(e) => e.preventDefault()}
                                    onClick={() => selectOption(opt.value)}
                                    className={cn(
                                        "w-full px-3 py-2.5 text-sm text-left hover:bg-accent transition-colors flex items-center justify-between",
                                        selectedValueText === opt.value && "bg-muted dark:bg-zinc-800/50"
                                    )}
                                >
                                    <span className="text-foreground/80 truncate">{opt.label}</span>
                                    {selectedValueText === opt.value && (
                                        <div className="h-1.5 w-1.5 rounded-full bg-emerald-500 dark:bg-emerald-400 flex-shrink-0" />
                                    )}
                                </button>
                            ))
                        ) : inputValue && dynamicOptions.allow_custom ? (
                            <button
                                type="button"
                                onMouseDown={(e) => e.preventDefault()}
                                onClick={() => selectOption(inputValue)}
                                className="w-full px-3 py-2.5 text-sm text-left hover:bg-accent transition-colors flex items-center gap-2"
                            >
                                <Edit3 className="h-3 w-3 text-muted-foreground dark:text-zinc-500" />
                                <span className="text-foreground/80">
                                    Use "<span className="text-foreground font-medium">{inputValue}</span>"
                                </span>
                            </button>
                        ) : (
                            <div className="px-3 py-3 text-xs text-muted-foreground dark:text-zinc-500 text-center">
                                {inputValue ? 'No matches found' : 'No options available'}
                            </div>
                        )}
                    </div>
                </div>,
                document.body
            )}
        </div>
    );
}

// ============================================================================
// Main Component
// ============================================================================

export function GenerationConfigField(props: GenerationConfigFieldProps) {
    const { input } = props;
    const fieldSchema = input.fieldSchema || {};

    // Check if this field has dynamic options
    const hasDynamicOptions = !!fieldSchema['x-dynamic-options'];

    if (hasDynamicOptions) {
        return <DynamicOptionsDropdown {...props} />;
    } else {
        return (
            <SimpleTextInput
                input={input}
                onValueChange={props.onValueChange}
                selectedValue={props.selectedValue}
            />
        );
    }
}
