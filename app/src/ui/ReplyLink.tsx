// A link in a reply, as both reply renderers (the chat's markdown and a channel message's) draw it: a raw URL reads
// short, one of NoClick's own links for a person reads as a chip naming what it does, and words the model chose stay.
// The full URL is always the target, so a tap opens it and a long-press copies it. Rules: lib/linkDisplay.ts.
import { Children, isValidElement, type ReactNode } from 'react';
import { ArrowUpRight } from 'lucide-react';
import { linkDisplay } from '@/lib/linkDisplay';
import { cn } from '@/ui/utils';

function wordsOf(node: ReactNode): string {
    return Children.toArray(node)
        .map((child) => {
            if (typeof child === 'string' || typeof child === 'number') return String(child);
            if (isValidElement<{ children?: ReactNode }>(child)) return wordsOf(child.props.children);
            return '';
        })
        .join('');
}

export function ReplyLink({ href, children, className }: { href?: string; children: ReactNode; className: string }) {
    const here = typeof window === 'undefined' ? undefined : window.location.host;
    const display = linkDisplay(href, wordsOf(children), here);
    if (display.kind === 'capability') {
        return (
            <a
                href={href}
                target="_blank"
                rel="noopener noreferrer"
                title={href}
                data-link-kind="capability"
                className="inline-flex max-w-full items-center gap-1 rounded-md border border-border bg-foreground/[0.04] px-1.5 py-0.5 align-baseline text-[0.92em] font-medium text-foreground no-underline transition-colors hover:bg-foreground/[0.09]"
            >
                <span className="truncate">{display.label}</span>
                <ArrowUpRight className="h-[0.9em] w-[0.9em] shrink-0 opacity-70" aria-hidden />
            </a>
        );
    }
    return (
        <a href={href} target="_blank" rel="noopener noreferrer" title={display.kind === 'short' ? href : undefined} className={cn(className, '[overflow-wrap:anywhere]')}>
            {display.kind === 'short' ? display.text : children}
        </a>
    );
}
