// InlineImageTag component renders an inline image preview within contenteditable text
// Shows loading state during upload and allows deletion via hover X button

import { useState, useRef } from 'react';
import { X, Loader2 } from 'lucide-react';
import { cn } from '~/lib/utils';
import { Progress } from '~/components/ui/progress';
import { TooltipPortal } from './TooltipPortal';
import { useSelectionHighlight, getSelectionHighlightClass } from '~/hooks/useSelectionHighlight';

export interface InlineImageTagProps {
    id: string;
    preview: string;
    isLoading?: boolean;
    progress?: number;
    onRemove?: (id: string) => void;
    className?: string;
}

export function InlineImageTag({ 
    id, 
    preview, 
    isLoading = false, 
    progress = 0, 
    onRemove,
    className 
}: InlineImageTagProps) {
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
                isVisible={isHoveringTag && !isLoading} 
                triggerRef={spanRef}
                placement="top"
                offset={8}
                delay={150}
            >
                <div className="bg-card border border-border dark:border-zinc-700 rounded-lg p-2 shadow-xl">
                    <img 
                        src={preview} 
                        alt="Preview"
                        className="max-w-xs max-h-64 object-contain rounded"
                    />
                </div>
            </TooltipPortal>

        <span
            ref={spanRef}
            onMouseEnter={() => setIsHoveringTag(true)}
            onMouseLeave={() => setIsHoveringTag(false)}
            contentEditable={false}
            className={cn(
                "inline-flex items-center mx-1 relative group cursor-default",
                "bg-secondary dark:bg-zinc-700/50 rounded-md p-0.5",
                "transition-colors duration-150",
                getSelectionHighlightClass(isSelected),
                className
            )}
            style={{ 
                verticalAlign: 'middle'
            }}
            data-paste-id={id}
            data-paste-type="image"
            data-paste-preview={preview}
        >
            <div className="relative">
                <img 
                    src={preview} 
                    alt="Pasted content"
                    className={cn(
                        "h-5 w-auto rounded",
                        isLoading && "opacity-50"
                    )}
                />
                
                {isLoading && (
                    <div className="absolute inset-0 flex items-center justify-center">
                        <Loader2 className="w-3 h-3 text-foreground animate-spin" />
                    </div>
                )}
                
                {isLoading && progress > 0 && (
                    <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-muted/50 rounded-b">
                        <Progress 
                            value={progress} 
                            className="h-full"
                        />
                    </div>
                )}
            </div>
            
            <button
                onClick={handleRemove}
                className={cn(
                    "absolute opacity-0 group-hover:opacity-100",
                    "bg-secondary rounded-full p-0.5",
                    "hover:bg-card transition-all duration-200",
                    "border border-border dark:border-zinc-600",
                    "z-[10000]"  // Higher than tooltips (z-[9999]) to ensure always clickable
                )}
                style={{
                    top: '-2px',
                    right: '-2px',
                    // Use transform to ensure it stays visible
                    transform: 'translate(25%, -25%)'
                }}
                aria-label="Remove image"
            >
                <X className="w-2.5 h-2.5 text-muted-foreground" />
            </button>
        </span>
        </>
    );
}
