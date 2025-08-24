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
    className?: string;
}

export function InlineDrawingTag({ 
    id, 
    screenshot, 
    isUpdating = false, 
    onRemove,
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
                <div className="bg-zinc-900 border border-zinc-700 rounded-lg p-2 shadow-xl">
                    <img 
                        src={screenshot} 
                        alt="Drawing Screenshot Preview"
                        className="max-w-xs max-h-64 object-contain rounded"
                    />
                    <div className="mt-1 text-xs text-zinc-400 text-center">
                        Auto-updating drawing screenshot
                    </div>
                </div>
            </TooltipPortal>

            <span
                ref={spanRef}
                onMouseEnter={() => setIsHoveringTag(true)}
                onMouseLeave={() => setIsHoveringTag(false)}
                contentEditable={false}
                className={cn(
                    "inline-flex items-center mx-1 relative group cursor-default",
                    "bg-purple-700/50 rounded-md p-0.5 border border-purple-500/30",
                    "transition-colors duration-150",
                    getSelectionHighlightClass(isSelected),
                    className
                )}
                style={{ 
                    verticalAlign: 'middle'
                }}
                data-drawing-id={id}
                data-drawing-type="screenshot"
                data-drawing-screenshot={screenshot}
            >
                <div className="relative flex items-center gap-1">
                    {/* Pen icon to indicate drawing content */}
                    <Pen className="w-3 h-3 text-purple-300" />
                    
                    <img 
                        src={screenshot} 
                        alt="Drawing screenshot"
                        className={cn(
                            "h-5 w-auto rounded",
                            isUpdating && "opacity-50"
                        )}
                    />
                    
                    <span className="text-xs text-purple-200 font-mono">
                        Drawing
                    </span>
                    
                    {isUpdating && (
                        <div className="absolute inset-0 flex items-center justify-center bg-purple-900/30 rounded">
                            <Loader2 className="w-3 h-3 text-purple-200 animate-spin" />
                        </div>
                    )}
                </div>
                
                <button
                    onClick={handleRemove}
                    className={cn(
                        "absolute opacity-0 group-hover:opacity-100",
                        "bg-purple-800 rounded-full p-0.5",
                        "hover:bg-purple-900 transition-all duration-200",
                        "border border-purple-600",
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
                    <X className="w-2.5 h-2.5 text-purple-200" />
                </button>
            </span>
        </>
    );
}