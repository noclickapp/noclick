/**
 * ShareRecipientInput - Unified autocomplete input for sharing resources.
 * Shows suggestions as user types:
 * - Organizations (by name or slug)
 * - Org members (by email or name)
 * - Any valid email (freeform entry)
 *
 * Inspired by the DroppableTextField autocomplete pattern.
 */

import { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import { Building2, Mail, ChevronDown, Loader2 } from 'lucide-react';
import { cn } from '~/lib/utils';
import { FIELD } from '~/components/shell/fields';
import { fuzzyFilter } from '~/utils/fuzzySearch';

export interface ShareSuggestion {
    type: 'organization' | 'user' | 'email';
    id?: string;           // org_id or user_id
    email?: string;        // email for users
    name: string;          // display name
    subtitle?: string;     // secondary text (e.g., "All members" for orgs)
    icon_url?: string;     // avatar/icon URL
}

interface ShareRecipientInputProps {
    /** Suggestions to show (orgs, members, etc.) */
    suggestions: ShareSuggestion[];
    /** Loading state while fetching suggestions */
    loading?: boolean;
    /** Currently selected permission level */
    permission: 'view' | 'edit';
    /** Callback when permission changes */
    onPermissionChange: (permission: 'view' | 'edit') => void;
    /** Callback when a recipient is selected */
    onSelect: (suggestion: ShareSuggestion) => void;
    /** Callback when submitting (for freeform email) */
    onSubmit?: (email: string) => void;
    /** Whether submission is in progress */
    submitting?: boolean;
    /** Placeholder text */
    placeholder?: string;
    /** Disabled state */
    disabled?: boolean;
    /** Hide permission selector (for resources like credentials that don't have view/edit) */
    hidePermission?: boolean;
}

// Helper to validate email format
function isValidEmail(email: string): boolean {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim());
}

// Get initials from name
function getInitials(name: string): string {
    return name.slice(0, 2).toUpperCase();
}

export function ShareRecipientInput({
    suggestions,
    loading = false,
    permission,
    onPermissionChange,
    onSelect,
    onSubmit,
    submitting = false,
    placeholder = "Add people by email, or a workspace",
    disabled = false,
    hidePermission = false,
}: ShareRecipientInputProps) {
    const [query, setQuery] = useState('');
    const [showDropdown, setShowDropdown] = useState(false);
    const [selectedIndex, setSelectedIndex] = useState(0);
    const inputRef = useRef<HTMLInputElement>(null);
    const dropdownRef = useRef<HTMLDivElement>(null);

    // Filter suggestions based on query
    const filteredSuggestions = useMemo(
        () =>
            fuzzyFilter(suggestions, query, s => [
                { text: s.name.toLowerCase(), weight: 1, fuzzy: true },
                { text: (s.email || '').toLowerCase(), weight: 0.6, fuzzy: true },
            ]),
        [suggestions, query]
    );

    // Check if query is a valid email not in suggestions
    const isNewEmail = useMemo(() => {
        if (!isValidEmail(query)) return false;
        const lowerQuery = query.toLowerCase().trim();
        return !suggestions.some(s => s.email?.toLowerCase() === lowerQuery);
    }, [query, suggestions]);

    // Combined suggestions: filtered + new email option if applicable
    const allSuggestions = useMemo(() => {
        const result = [...filteredSuggestions];
        if (isNewEmail) {
            result.push({
                type: 'email',
                email: query.trim().toLowerCase(),
                name: query.trim().toLowerCase(),
                subtitle: 'Send invite',
            });
        }
        return result;
    }, [filteredSuggestions, isNewEmail, query]);

    // Reset selected index when suggestions change
    useEffect(() => {
        setSelectedIndex(0);
    }, [allSuggestions.length]);

    // Handle input change
    const handleChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
        setQuery(e.target.value);
        setShowDropdown(true);
    }, []);

    // Handle selection
    const handleSelect = useCallback((suggestion: ShareSuggestion) => {
        if (suggestion.type === 'email' && onSubmit) {
            onSubmit(suggestion.email!);
        } else {
            onSelect(suggestion);
        }
        setQuery('');
        setShowDropdown(false);
        inputRef.current?.focus();
    }, [onSelect, onSubmit]);

    // Keyboard navigation
    const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
        if (!showDropdown || allSuggestions.length === 0) {
            // If Enter pressed with valid email, submit
            if (e.key === 'Enter' && isNewEmail && onSubmit) {
                e.preventDefault();
                onSubmit(query.trim().toLowerCase());
                setQuery('');
            }
            return;
        }

        switch (e.key) {
            case 'ArrowDown':
                e.preventDefault();
                setSelectedIndex(prev => (prev + 1) % allSuggestions.length);
                break;
            case 'ArrowUp':
                e.preventDefault();
                setSelectedIndex(prev => (prev - 1 + allSuggestions.length) % allSuggestions.length);
                break;
            case 'Enter':
            case 'Tab':
                e.preventDefault();
                handleSelect(allSuggestions[selectedIndex]);
                break;
            case 'Escape':
                e.preventDefault();
                setShowDropdown(false);
                break;
        }
    }, [showDropdown, allSuggestions, selectedIndex, handleSelect, isNewEmail, query, onSubmit]);

    // Close dropdown when clicking outside
    useEffect(() => {
        const handleClickOutside = (e: MouseEvent) => {
            if (
                dropdownRef.current && !dropdownRef.current.contains(e.target as Node) &&
                inputRef.current && !inputRef.current.contains(e.target as Node)
            ) {
                setShowDropdown(false);
            }
        };

        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, []);

    // Scroll selected item into view
    useEffect(() => {
        if (showDropdown && dropdownRef.current) {
            const selectedEl = dropdownRef.current.querySelector(`[data-index="${selectedIndex}"]`);
            selectedEl?.scrollIntoView({ block: 'nearest' });
        }
    }, [selectedIndex, showDropdown]);

    // A suggestion's face: its picture, else a neutral tile (square for a workspace, round for a person).
    const getSuggestionIcon = (suggestion: ShareSuggestion) => {
        const shape = suggestion.type === 'organization' ? 'rounded-md' : 'rounded-full';
        if (suggestion.icon_url) return <img src={suggestion.icon_url} alt="" className={cn('h-7 w-7 shrink-0 object-cover', shape)} />;
        return (
            <span className={cn('grid h-7 w-7 shrink-0 place-items-center bg-foreground/[0.08] text-[10.5px] font-medium text-foreground/80', shape)}>
                {suggestion.type === 'organization' ? <Building2 className="h-3.5 w-3.5" /> : suggestion.type === 'email' ? <Mail className="h-3.5 w-3.5" /> : getInitials(suggestion.name)}
            </span>
        );
    };

    return (
        <div>
            <div className="flex items-center gap-2">
                <input
                    ref={inputRef}
                    type="text"
                    value={query}
                    onChange={handleChange}
                    onKeyDown={handleKeyDown}
                    onFocus={() => setShowDropdown(true)}
                    placeholder={placeholder}
                    disabled={disabled || submitting}
                    aria-label="Add people"
                    className={cn(FIELD, 'min-w-0 flex-1')}
                />
                {/* Hidden for credentials and saved outputs, which are only ever shared to view. */}
                {!hidePermission && (
                    <button
                        type="button"
                        onClick={() => onPermissionChange(permission === 'view' ? 'edit' : 'view')}
                        disabled={disabled || submitting}
                        className="inline-flex h-10 shrink-0 items-center gap-1.5 rounded-xl border border-border px-3 text-[13px] text-foreground/85 transition-colors hover:bg-foreground/[0.04] disabled:opacity-50 dark:border-foreground/[0.1]"
                    >
                        {permission === 'edit' ? 'Can edit' : 'Can view'}
                        <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
                    </button>
                )}
            </div>

            {/* In the flow under the field, so a dialog's scrolling body never clips it. */}
            {showDropdown && (query.trim() || suggestions.length > 0) && (
                <div ref={dropdownRef} className="mt-1.5">
                    {loading ? (
                        <div className="flex items-center justify-center py-3">
                            <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                        </div>
                    ) : allSuggestions.length > 0 ? (
                        <div className="max-h-56 overflow-y-auto scrollbar-subtle">
                            {allSuggestions.map((suggestion, index) => (
                                <button
                                    key={suggestion.id || suggestion.email || index}
                                    type="button"
                                    data-index={index}
                                    onMouseDown={(e) => e.preventDefault()}
                                    onClick={() => handleSelect(suggestion)}
                                    onMouseEnter={() => setSelectedIndex(index)}
                                    className={cn('flex w-full items-center gap-3 rounded-xl px-2 py-1.5 text-left transition-colors', index === selectedIndex && 'bg-foreground/[0.06]')}
                                >
                                    {getSuggestionIcon(suggestion)}
                                    <span className="min-w-0 flex-1">
                                        <span className="block truncate text-[14px] text-foreground">{suggestion.name}</span>
                                        {suggestion.subtitle && <span className="block truncate text-[12px] text-muted-foreground">{suggestion.subtitle}</span>}
                                    </span>
                                    <span className="shrink-0 text-[12px] text-muted-foreground">{suggestion.type === 'organization' ? 'Workspace' : suggestion.type === 'email' ? 'Invite' : 'Person'}</span>
                                </button>
                            ))}
                        </div>
                    ) : query.trim() && !isNewEmail ? (
                        <p className="px-2 py-2 text-[13px] text-muted-foreground">No matches. Type an email address to invite someone.</p>
                    ) : null}
                </div>
            )}
        </div>
    );
}
