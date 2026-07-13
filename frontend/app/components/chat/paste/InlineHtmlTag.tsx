// InlineHtmlTag component renders an inline HTML element tag within contenteditable text
// Allows users to reference selected HTML elements with contextual text around them

import { useState, useRef } from 'react';
import { X, Code2 } from 'lucide-react';
import { cn } from '~/lib/utils';
import { useSelectionHighlight, getSelectionHighlightClass } from '~/hooks/useSelectionHighlight';

export interface InlineHtmlTagProps {
    id: string;
    tagName: string;
    noclickId: string;
    onRemove?: (id: string) => void;
    onHover?: (noclickId: string) => void;
    onMouseLeave?: () => void;
    className?: string;
}

export function InlineHtmlTag({
    id,
    tagName,
    noclickId,
    onRemove,
    onHover,
    onMouseLeave,
    className
}: InlineHtmlTagProps) {
    const [isHoveringTag, setIsHoveringTag] = useState(false);
    const spanRef = useRef<HTMLSpanElement>(null);
    const isSelected = useSelectionHighlight(spanRef);

    const handleRemove = (e: React.MouseEvent) => {
        e.preventDefault();
        e.stopPropagation();
        onRemove?.(id);
    };

    const handleMouseEnter = () => {
        setIsHoveringTag(true);
        onHover?.(noclickId);
    };

    const handleMouseLeave = () => {
        setIsHoveringTag(false);
        onMouseLeave?.();
    };

    return (
        <span
            ref={spanRef}
            onMouseEnter={handleMouseEnter}
            onMouseLeave={handleMouseLeave}
            contentEditable={false}
            className={cn(
                "inline-flex items-center mx-1 relative group",
                "bg-primary/80 rounded-md px-1.5 py-0.5 border border-primary/70",
                "transition-all duration-150",
                "hover:bg-primary/90 hover:border-primary/80",
                getSelectionHighlightClass(isSelected),
                className
            )}
            style={{
                verticalAlign: 'middle',
                cursor: 'default'
            }}
            data-html-element-id={id}
            data-html-element-tagname={tagName}
            data-html-element-noclickid={noclickId}
            title={`Selected ${tagName} element`}
        >
            <div className="relative flex items-center gap-1">
                {/* Code icon to indicate HTML element */}
                <Code2 className="w-3 h-3 text-primary-foreground" />

                <span className="text-xs text-primary-foreground font-mono lowercase">
                    {tagName.toLowerCase()}
                </span>
            </div>

            <button
                onClick={handleRemove}
                className={cn(
                    "absolute opacity-0 group-hover:opacity-100",
                    "bg-primary/80 rounded-full p-0.5",
                    "hover:bg-primary/90 transition-all duration-200",
                    "border border-primary/70",
                    "z-[10000]"  // Higher than tooltips to ensure always clickable
                )}
                style={{
                    top: '-2px',
                    right: '-2px',
                    // Use transform to ensure it stays visible
                    transform: 'translate(25%, -25%)'
                }}
                aria-label={`Remove ${tagName} element`}
            >
                <X className="w-2.5 h-2.5 text-primary-foreground" />
            </button>
        </span>
    );
}