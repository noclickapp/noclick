// Shared inline text editor component for click-to-edit text fields.
// Used by AppNavbar for workflow titles and by node labels.
// Features: auto-sizing input, cursor placement at click point, enter/escape handling.

import { useState, useRef, useEffect, useCallback } from 'react';

interface InlineTextEditorProps {
    value: string;
    placeholder?: string;
    onSave: (newValue: string) => void;
    className?: string;
    inputClassName?: string;
    spanClassName?: string;
    maxWidth?: number;
    /** If true, shows lighter text color for placeholder-like default values */
    isDefaultValue?: boolean;
    /** If true, adds text shadow for better visibility on dark backgrounds */
    textShadow?: boolean;
    /** If true, allows text to wrap to multiple lines instead of truncating */
    wrap?: boolean;
    /** Counter signal; each increment enters edit mode (full text selected).
     *  Use from external triggers like the node right-click "Rename" menu item. */
    startEditingSignal?: number;
}

export function InlineTextEditor({
    value,
    placeholder = '',
    onSave,
    className = '',
    inputClassName = '',
    spanClassName = '',
    maxWidth = 180,
    isDefaultValue = false,
    textShadow = false,
    wrap = false,
    startEditingSignal,
}: InlineTextEditorProps) {
    const [isEditing, setIsEditing] = useState(false);
    const [editValue, setEditValue] = useState(value);
    const inputRef = useRef<HTMLInputElement>(null);

    // Update editValue when external value changes
    useEffect(() => {
        if (!isEditing) {
            setEditValue(value);
        }
    }, [value, isEditing]);

    // Focus input when entering edit mode - cursor position is set by click handler
    useEffect(() => {
        if (isEditing && inputRef.current) {
            inputRef.current.focus();
        }
    }, [isEditing]);

    // External "start editing" trigger (e.g. node right-click Rename). Each
    // increment of startEditingSignal opens the editor and selects all text.
    // Skip the initial mount (signal=0 / undefined) so we don't enter edit mode
    // before the user asks. RAF gives React a tick to render the input.
    const lastSignalRef = useRef<number | undefined>(startEditingSignal);
    useEffect(() => {
        if (startEditingSignal === undefined) return;
        if (startEditingSignal === lastSignalRef.current) return;
        lastSignalRef.current = startEditingSignal;
        setIsEditing(true);
        requestAnimationFrame(() => inputRef.current?.select());
    }, [startEditingSignal]);

    const handleSave = useCallback(() => {
        const trimmedValue = editValue.trim();
        if (trimmedValue !== value) {
            onSave(trimmedValue);
            // Update local state to saved value immediately to prevent useEffect
            // from resetting it to the old value before parent state updates
            setEditValue(trimmedValue);
        }
        setIsEditing(false);
    }, [editValue, value, onSave]);

    const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            handleSave();
        } else if (e.key === 'Escape') {
            e.preventDefault();
            setEditValue(value);
            setIsEditing(false);
        }
        e.stopPropagation();
    }, [handleSave, value]);

    const handleTextClick = useCallback((e: React.MouseEvent<HTMLSpanElement>) => {
        // Get click position relative to the text to place cursor correctly
        const span = e.currentTarget;
        const rect = span.getBoundingClientRect();
        const clickX = e.clientX - rect.left;

        setIsEditing(true);

        // After state updates and input renders, set cursor position
        requestAnimationFrame(() => {
            if (!inputRef.current) return;

            // Create a temporary span to measure character positions
            const text = editValue;
            const tempSpan = document.createElement('span');
            tempSpan.style.cssText = window.getComputedStyle(inputRef.current).cssText;
            tempSpan.style.position = 'absolute';
            tempSpan.style.visibility = 'hidden';
            tempSpan.style.whiteSpace = 'pre';
            document.body.appendChild(tempSpan);

            // Find the character position closest to click
            let cursorPos = text.length;
            for (let i = 0; i <= text.length; i++) {
                tempSpan.textContent = text.substring(0, i);
                if (tempSpan.offsetWidth >= clickX) {
                    cursorPos = i;
                    break;
                }
            }

            document.body.removeChild(tempSpan);
            inputRef.current.setSelectionRange(cursorPos, cursorPos);
        });
    }, [editValue]);

    // Use editValue for display since it's kept in sync with value prop via useEffect,
    // and is updated immediately on save before parent state propagates
    const displayValue = editValue || placeholder;

    return (
        <div className={`relative ${className}`} style={{ maxWidth }}>
            {isEditing ? (
                <>
                    {/* Hidden span to measure text width - makes input auto-size */}
                    <span
                        className={`block invisible whitespace-pre text-sm font-medium leading-normal px-1.5 py-0.5 ${inputClassName}`}
                        style={{ maxWidth }}
                    >
                        {editValue || placeholder || ' '}
                    </span>
                    <input
                        ref={inputRef}
                        type="text"
                        value={editValue}
                        onChange={(e) => setEditValue(e.target.value)}
                        onBlur={handleSave}
                        onKeyDown={handleKeyDown}
                        placeholder={placeholder}
                        className={`absolute inset-0 text-sm font-medium leading-normal text-foreground bg-transparent border border-foreground/30 rounded px-1.5 py-0.5 outline-none focus:border-foreground/50 w-full ${inputClassName}`}
                    />
                </>
            ) : (
                <span
                    onClick={handleTextClick}
                    className={`text-sm font-medium block leading-normal cursor-text border border-transparent rounded px-1.5 py-0.5 transition-colors hover:border-foreground/20 ${wrap ? 'whitespace-normal text-center' : 'whitespace-nowrap overflow-hidden text-ellipsis'} ${isDefaultValue ? 'text-muted-foreground hover:text-foreground' : 'text-foreground hover:text-foreground'} ${spanClassName}`}
                    style={{
                        // Legibility halo that matches the canvas: a dark glow on
                        // the dark canvas, a light glow on the light canvas — so
                        // labels don't read as heavy black blobs in light mode.
                        textShadow: textShadow ? '0 1px 3px hsl(var(--background) / 0.8)' : undefined,
                        maxWidth,
                    }}
                    title={isDefaultValue ? `${displayValue} (click to customize)` : `${displayValue} (click to edit)`}
                >
                    {displayValue}
                </span>
            )}
        </div>
    );
}
