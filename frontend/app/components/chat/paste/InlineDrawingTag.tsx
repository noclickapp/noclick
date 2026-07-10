// InlineDrawingTag component renders an inline drawing screenshot preview within contenteditable text
// Auto-updating tag that appears when drawing starts with purple styling to distinguish from pasted content

import { useState, useRef } from 'react';
import { X, Pen, Loader2 } from 'lucide-react';
import { cn } from '~/lib/utils';
import { TooltipPortal } from './TooltipPortal';
import { useSelectionHighlight, getSelectionHighlightClass } from '~/hooks/useSelectionHighlight';

export interface InlineDrawingTagProps {
    id: string;
    screenshot: string;
    isUpdating?: boolean;
    onRemove?: (id: string) => void;
    onClick?: () => void;
    className?: string;
}

export function InlineDrawingTag({ 
    id, 
    screenshot, 
    isUpdating = false, 
    onRemove,
    onClick,
    className 
}: InlineDrawingTagProps) {
    const [isHoveringTag, setIsHoveringTag] = useState(false);
    const spanRef = useRef<HTMLSpanElement>(null);
    const isSelected = useSelectionHighlight(spanRef);
    
    const handleRemove = (e: React.MouseEvent) => {
        e.preventDefault();
        e.stopPropagation();
        onRemove?.(id);
    };

    const handleClick = (e: React.MouseEvent) => {
        if (onClick) {
            e.preventDefault();
            e.stopPropagation();
            onClick();
        }
    };

    return (
        <>
            {/* Tooltip rendered via portal */}
            <TooltipPortal 
                isVisible={isHoveringTag && !isUpdating} 
                triggerRef={spanRef}
                placement="top"
                offset={8}
                delay={150}
            >
                <div className="bg-card border border-border rounded-lg p-2 shadow-xl">
                    <img 
                        src={screenshot} 
                        alt="Drawing Screenshot Preview"
                        className="max-w-xs max-h-64 object-contain rounded"
                    />
                    <div className="mt-1 text-xs text-muted-foreground text-center">
                        Auto-updating drawing screenshot
                    </div>
                </div>
            </TooltipPortal>

            <span
                ref={spanRef}
                onMouseEnter={() => setIsHoveringTag(true)}
                onMouseLeave={() => setIsHoveringTag(false)}
                onClick={handleClick}
                contentEditable={false}
                className={cn(
                    "inline-flex items-center mx-1 relative group",
                    "bg-primary/80 rounded-md p-0.5 border border-primary/70",
                    "transition-colors duration-150",
                    onClick ? "cursor-pointer hover:bg-primary/90 hover:border-primary/80" : "cursor-default",
                    getSelectionHighlightClass(isSelected),
                    className
                )}
                style={{ 
                    verticalAlign: 'middle',
                    cursor: onClick ? 'pointer' : 'default'
                }}
                data-drawing-id={id}
                data-drawing-type="screenshot"
                data-drawing-screenshot={screenshot}
                title={onClick ? "Click to toggle drawing mode" : undefined}
            >
                <div className="relative flex items-center gap-1">
                    {/* Pen icon to indicate drawing content */}
                    <Pen className="w-3 h-3 text-primary-foreground" />
                    
                    <img
                        src={screenshot}
                        alt="Drawing screenshot"
                        className={cn(
                            "h-4 w-auto rounded",
                            isUpdating && "opacity-50"
                        )}
                    />
                    
                    <span className="text-xs text-primary-foreground font-mono">
                        Drawing
                    </span>

                    {isUpdating && (
                        <div className="absolute inset-0 flex items-center justify-center bg-primary/30 rounded">
                            <Loader2 className="w-3 h-3 text-primary-foreground animate-spin" />
                        </div>
                    )}
                </div>
                
                <button
                    onClick={handleRemove}
                    className={cn(
                        "absolute opacity-0 group-hover:opacity-100",
                        "bg-primary/80 rounded-full p-0.5",
                        "hover:bg-primary/90 transition-all duration-200",
                        "border border-primary/70",
                        "z-[10000]"  // Higher than tooltips (z-[9999]) to ensure always clickable
                    )}
                    style={{
                        top: '-2px',
                        right: '-2px',
                        // Use transform to ensure it stays visible
                        transform: 'translate(25%, -25%)'
                    }}
                    aria-label="Remove drawing screenshot"
                >
                    <X className="w-2.5 h-2.5 text-primary-foreground" />
                </button>
            </span>
        </>
    );
}