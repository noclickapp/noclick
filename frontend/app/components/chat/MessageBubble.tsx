// The chat message bubble chrome, extracted from MessagesView so the bubble
// look — surface, border, radius, padding — lives in one place. Class strings
// are the single source of truth for the assistant/user bubble.
import { cn } from '~/lib/utils';
import type { CSSProperties, ReactNode } from 'react';

const BASE = 'text-sm p-2.5 rounded-lg font-medium transition-all duration-300 ease-out';
export const ASSISTANT_BUBBLE_CLASS = cn(BASE, 'bg-white/10 backdrop-blur-sm border border-white/20 text-white mr-auto rounded-tl-none');
export const USER_BUBBLE_CLASS = cn(BASE, 'bg-zinc-900 text-white ml-auto rounded-tr-none');

export function MessageBubble({
    isUser = false,
    bubbleRef,
    style,
    className,
    children,
}: {
    isUser?: boolean;
    bubbleRef?: (el: HTMLDivElement | null) => void;
    style?: CSSProperties;
    className?: string;
    children: ReactNode;
}) {
    return (
        <div
            ref={bubbleRef}
            className={cn(isUser ? USER_BUBBLE_CLASS : ASSISTANT_BUBBLE_CLASS, className)}
            style={style}
        >
            {children}
        </div>
    );
}
