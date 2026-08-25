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
import { Building2, User, Mail, ChevronDown, Check, Loader2 } from 'lucide-react';
import { cn } from '~/lib/utils';
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
    placeholder = "Add people or organizations...",
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

    // Get icon for suggestion type (compact: 5x5 instead of 6x6)
    const getSuggestionIcon = (suggestion: ShareSuggestion) => {
        if (suggestion.type === 'organization') {
            if (suggestion.icon_url) {
                return <img src={suggestion.icon_url} alt="" className="w-5 h-5 rounded-full" />;
            }
            return (
                <div className="w-5 h-5 rounded-full bg-blue-500/20 flex items-center justify-center">
                    <Building2 className="h-3 w-3 text-blue-600 dark:text-blue-400" />
                </div>
            );
        }
        if (suggestion.type === 'email') {
            return (
                <div className="w-5 h-5 rounded-full bg-foreground/20 flex items-center justify-center">
                    <Mail className="h-3 w-3 text-muted-foreground" />
                </div>
            );
        }
        // User
        if (suggestion.icon_url) {
            return <img src={suggestion.icon_url} alt="" className="w-5 h-5 rounded-full" />;
        }
        return (
            <div className="w-5 h-5 rounded-full bg-foreground/20 flex items-center justify-center text-[9px] font-medium text-foreground/80">
                {getInitials(suggestion.name)}
            </div>
        );
    };

    return (
        <div className="relative">
            {/* Input row - compact */}
            <div className="flex items-center gap-1.5">
                <div className="flex-1 relative">
                    <input
                        ref={inputRef}
                        type="text"
                        value={query}
                        onChange={handleChange}
                        onKeyDown={handleKeyDown}
                        onFocus={() => setShowDropdown(true)}
                        placeholder={placeholder}
                        disabled={disabled || submitting}
                        className={cn(
                            "w-full px-2.5 py-1.5 text-sm rounded-md transition-all",
                            "bg-card/80 border border-border",
                            "text-foreground placeholder:text-[hsl(var(--placeholder))]",
                            "focus:outline-none focus:border-border dark:focus:border-zinc-700",
                            (disabled || submitting) && "opacity-50 cursor-not-allowed"
                        )}
                    />
                </div>

                {/* Permission selector - compact (hidden for credentials/saved outputs) */}
                {!hidePermission && (
                    <button
                        type="button"
                        onClick={() => onPermissionChange(permission === 'view' ? 'edit' : 'view')}
                        disabled={disabled || submitting}
                        className={cn(
                            "flex items-center gap-1 px-2 py-1.5 text-xs rounded-md transition-all whitespace-nowrap",
                            "bg-card/80 border border-border text-muted-foreground",
                            "hover:bg-accent hover:text-foreground",
                            (disabled || submitting) && "opacity-50 cursor-not-allowed"
                        )}
                    >
                        {permission === 'edit' ? 'Can edit' : 'Can view'}
                        <ChevronDown className="h-2.5 w-2.5 opacity-60" />
                    </button>
                )}
            </div>

            {/* Dropdown - compact */}
            {showDropdown && (query.trim() || suggestions.length > 0) && (
                <div
                    ref={dropdownRef}
                    className="absolute z-50 w-full mt-1 bg-card border border-border rounded-md shadow-xl overflow-hidden"
                >
                    {loading ? (
                        <div className="flex items-center justify-center py-3">
                            <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground dark:text-zinc-500" />
                        </div>
                    ) : allSuggestions.length > 0 ? (
                        <div className="max-h-48 overflow-y-auto py-1">
                            {allSuggestions.map((suggestion, index) => (
                                <button
                                    key={suggestion.id || suggestion.email || index}
                                    type="button"
                                    data-index={index}
                                    onMouseDown={(e) => e.preventDefault()}
                                    onClick={() => handleSelect(suggestion)}
                                    onMouseEnter={() => setSelectedIndex(index)}
                                    className={cn(
                                        "w-full px-2.5 py-1.5 flex items-center gap-2 transition-colors",
                                        index === selectedIndex
                                            ? "bg-secondary"
                                            : "hover:bg-accent dark:hover:bg-zinc-800/50"
                                    )}
                                >
                                    {getSuggestionIcon(suggestion)}
                                    <div className="flex-1 min-w-0 text-left">
                                        <div className="text-xs text-foreground truncate">
                                            {suggestion.name}
                                        </div>
                                        {suggestion.subtitle && (
                                            <div className="text-[10px] text-muted-foreground dark:text-zinc-500 truncate">
                                                {suggestion.subtitle}
                                            </div>
                                        )}
                                    </div>
                                    {/* Type badge - subtle */}
                                    <span className={cn(
                                        "text-[9px] px-1 py-0.5 rounded font-medium",
                                        suggestion.type === 'organization'
                                            ? "bg-blue-500/15 text-blue-600 dark:text-blue-400"
                                            : "bg-secondary text-muted-foreground dark:text-zinc-500"
                                    )}>
                                        {suggestion.type === 'organization' ? 'org' : 'user'}
                                    </span>
                                </button>
                            ))}
                        </div>
                    ) : query.trim() && !isNewEmail ? (
                        <div className="px-2.5 py-3 text-xs text-muted-foreground dark:text-zinc-500 text-center">
                            No matches. Enter a valid email to invite.
                        </div>
                    ) : null}
                </div>
            )}
        </div>
    );
}
