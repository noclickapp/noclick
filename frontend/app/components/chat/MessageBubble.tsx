// The chat message bubble chrome, extracted from MessagesView so the bubble
// look lives in one place. Class strings are the single source of truth for
// the assistant/user bubble.
import { cn } from '~/lib/utils';
import type { CSSProperties, ReactNode } from 'react';

const BASE = 'text-[14px] leading-relaxed text-foreground transition-all duration-300 ease-out';
// The same anatomy as the coordinator chat: the assistant speaks as plain text
// on the page, the person's turns sit in a soft bubble on the right.
export const ASSISTANT_BUBBLE_CLASS = cn(BASE, 'mr-auto py-0.5');
export const USER_BUBBLE_CLASS = cn(BASE, 'ml-auto rounded-2xl rounded-br-sm bg-secondary px-3.5 py-2');

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
            className={cn(
                isUser ? USER_BUBBLE_CLASS : ASSISTANT_BUBBLE_CLASS,
                className
            )}
            style={style}
        >
            {children}
        </div>
    );
}
