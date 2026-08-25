// This isn't a part of shadcn, was added manually
import { ReactNode, useState, useRef, useEffect } from 'react';
import { ArrowLeft } from 'lucide-react';
import { Button } from '~/components/ui/button';

interface AppNavbarProps {
    title?: string;
    onTitleChange?: (newTitle: string) => void;
    onBack?: () => void;
    leftContent?: ReactNode;
    centerContent?: ReactNode;
    rightContent?: ReactNode;
    compact?: boolean;
    /** Attached to the bar's root element so callers can measure its width
     * (the bar is often narrower than the viewport — side panels eat space). */
    rootRef?: React.Ref<HTMLDivElement>;
}

export function AppNavbar({ title, onTitleChange, onBack, leftContent, centerContent, rightContent, compact = false, rootRef }: AppNavbarProps) {
    const [isEditing, setIsEditing] = useState(false);
    const [editValue, setEditValue] = useState(title || '');
    const inputRef = useRef<HTMLInputElement>(null);

    // Update editValue when title prop changes
    useEffect(() => {
        if (!isEditing) {
            setEditValue(title || '');
        }
    }, [title, isEditing]);

    // Focus input when entering edit mode - cursor position is set by click handler
    useEffect(() => {
        if (isEditing && inputRef.current) {
            inputRef.current.focus();
        }
    }, [isEditing]);

    const handleSave = () => {
        const trimmedValue = editValue.trim();
        if (trimmedValue && trimmedValue !== title && onTitleChange) {
            onTitleChange(trimmedValue);
        }
        setIsEditing(false);
    };

    const handleKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === 'Enter') {
            handleSave();
        } else if (e.key === 'Escape') {
            setEditValue(title || '');
            setIsEditing(false);
        }
    };

    const handleTitleClick = (e: React.MouseEvent<HTMLSpanElement>) => {
        if (!onTitleChange) return;

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
    };

    return (
        <div ref={rootRef} className={`shrink-0 h-12 ${compact ? 'px-2' : 'px-3'} bg-background/95 dark:bg-zinc-950/95 backdrop-blur-md border-b-2 border-border/80 dark:border-zinc-800/80 flex justify-between items-center shadow-lg dark:shadow-black/20 relative z-20 select-none overflow-hidden before:absolute before:inset-x-0 before:top-0 before:h-px before:bg-gradient-to-r before:from-transparent before:via-border dark:before:via-zinc-600/50 before:to-transparent`}>
            <div className={`flex items-center ${compact ? 'gap-2' : 'gap-3'}`}>
                {/* Back button - only show if onBack is provided */}
                {onBack && (
                    <Button
                        variant="ghost"
                        size="sm"
                        onClick={onBack}
                        className="text-muted-foreground hover:text-foreground hover:bg-accent dark:hover:bg-zinc-800/50 transition-colors rounded-full h-8 w-8 p-0"
                    >
                        <ArrowLeft className="h-4 w-4" />
                    </Button>
                )}

                {/* App title - editable if onTitleChange is provided */}
                {title && (
                    <div className="flex items-center">
                        {isEditing ? (
                            <div className="relative -mx-1.5 -my-0.5 max-w-[300px]">
                                {/* Hidden span to measure text width */}
                                <span className="block invisible whitespace-pre text-sm font-medium px-1.5 py-0.5 max-w-[300px]">
                                    {editValue || ' '}
                                </span>
                                <input
                                    ref={inputRef}
                                    type="text"
                                    value={editValue}
                                    onChange={(e) => setEditValue(e.target.value)}
                                    onBlur={handleSave}
                                    onKeyDown={handleKeyDown}
                                    className="absolute top-px left-0 right-0 bottom-0 text-sm font-medium text-foreground bg-transparent border border-foreground/30 rounded px-1.5 outline-none w-full leading-[1.7]"
                                />
                            </div>
                        ) : (
                            <span
                                onClick={handleTitleClick}
                                className={`text-sm font-medium text-foreground/80 truncate ${compact ? 'max-w-[120px]' : 'max-w-[200px]'} border border-transparent rounded px-1.5 py-0.5 -mx-1.5 -my-0.5 ${onTitleChange ? 'hover:text-foreground hover:border-foreground/20 cursor-text transition-colors' : ''}`}
                            >
                                {title}
                            </span>
                        )}
                        {!compact && <div className="w-px h-4 bg-foreground/20 mx-3" />}
                    </div>
                )}

                {/* Additional left content */}
                {leftContent}
            </div>
            
            {/* Center content */}
            {centerContent && (
                <div className="flex-grow flex items-center justify-center">
                    {centerContent}
                </div>
            )}
            
            {/* If no center content, use a simple spacer */}
            {!centerContent && <div className="flex-grow" />}
            
            {/* Right content */}
            <div className={`flex items-center ${compact ? 'gap-2' : 'gap-3'}`}>
                {rightContent}
            </div>
        </div>
    );
}
