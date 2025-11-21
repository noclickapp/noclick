// Inline context tag component for displaying @mentions with highlighted background
// Shows selected context options as tags to distinguish them from regular text

import { memo, useRef } from 'react';
import { X } from 'lucide-react';
import { cn } from '~/lib/utils';
import { useSelectionHighlight, getSelectionHighlightClass } from '~/hooks/useSelectionHighlight';

interface InlineContextTagProps {
    id: string;
    value: string; // The context value (e.g., "Files & Documents")
    onRemove: (id: string) => void;
}

export const InlineContextTag = memo(({
    id,
    value,
    onRemove
}: InlineContextTagProps) => {
    const spanRef = useRef<HTMLSpanElement>(null);
    const isSelected = useSelectionHighlight(spanRef);

    const handleRemove = (e: React.MouseEvent) => {
        e.preventDefault();
        e.stopPropagation();
        onRemove(id);
    };

    return (
        <span
            ref={spanRef}
            contentEditable={false}
            className={cn(
                'inline-flex items-center mx-0.5 relative group',
                'bg-white/80 rounded px-1 py-0 border border-white/70',
                'transition-all duration-150',
                'hover:bg-white/90 hover:border-white/80',
                getSelectionHighlightClass(isSelected)
            )}
            style={{
                verticalAlign: 'middle',
                cursor: 'default'
            }}
            data-context-id={id}
            data-context-value={value}
            title={`Context: ${value}`}
        >
            <div className="relative flex items-center gap-0.5">
                <span className="text-xs text-blue-600 font-medium">@</span>
                <span className="text-xs text-zinc-800">{value}</span>
            </div>
        </span>
    );
});

InlineContextTag.displayName = 'InlineContextTag';
