// InlineTextTag component renders an inline tag for large pasted text content
// Displays line count and allows deletion via hover X button

import { useState, useRef } from 'react';
import { X, FileText } from 'lucide-react';
import { cn } from '~/lib/utils';
import { TooltipPortal } from './TooltipPortal';
import { useSelectionHighlight, getSelectionHighlightClass } from '~/hooks/useSelectionHighlight';

export interface InlineTextTagProps {
    id: string;
    lineCount: number;
    content: string;
    onRemove?: (id: string) => void;
    className?: string;
}

export function InlineTextTag({ 
    id, 
    lineCount, 
    content,
    onRemove,
    className 
}: InlineTextTagProps) {
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
                isVisible={isHoveringTag} 
                triggerRef={spanRef}
                placement="top"
                offset={8}
                delay={150}
            >
                <div className="bg-zinc-900 border border-zinc-700 rounded-lg p-3 shadow-xl max-w-md">
                    <div className="max-h-48 overflow-y-auto whitespace-pre-wrap text-xs text-zinc-300 scrollbar-subtle">
                        {content}
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
                "bg-white/80 rounded-md px-2 py-0.5 border border-white/70",
                "transition-colors duration-150",
                getSelectionHighlightClass(isSelected),
                className
            )}
            style={{ 
                verticalAlign: 'middle'
            }}
            data-paste-id={id}
            data-paste-type="text"
            data-paste-content={content}
            data-paste-lines={lineCount}
        >
            <FileText className="w-3 h-3 text-zinc-800 mr-1" />
            <span className="text-xs text-zinc-800">
                Pasted {lineCount} lines
            </span>
            
            <button
                onClick={handleRemove}
                className={cn(
                    "absolute opacity-0 group-hover:opacity-100",
                    "bg-white/80 rounded-full p-0.5",
                    "hover:bg-white/90 transition-all duration-200",
                    "border border-white/70",
                    "z-[10000]"  // Higher than tooltips (z-[9999]) to ensure always clickable
                )}
                style={{
                    top: '-2px',
                    right: '-2px',
                    // Use transform to ensure it stays visible
                    transform: 'translate(25%, -25%)'
                }}
                aria-label="Remove pasted text"
            >
                <X className="w-2.5 h-2.5 text-zinc-800" />
            </button>
        </span>
        </>
    );
}