// Lazy boundary for the chat markdown renderer. The real renderer pulls
// react-markdown + remark/rehype + katex + Prism + mermaid + panzoom (~1.68MB
// raw / ~514KB gz), which used to evaluate eagerly on dashboard mount because
// MessagesView (always mounted in the chat) statically imported it. That was the
// single biggest remaining JS-eval cost on the dashboard's TTI path.
//
// This wrapper defers it: until the chunk loads it renders the raw text (so
// messages are never blank), and it warms the chunk on idle so streaming/long
// messages don't flash plain text. On a fresh dashboard with no messages the
// chunk is never even fetched until something actually renders markdown.
import { lazy, Suspense, useEffect } from 'react';
import { cn } from '~/lib/utils';
import type { MarkdownRendererProps } from './MarkdownRenderer';

const importRenderer = () => import('./MarkdownRenderer');
const MarkdownRendererImpl = lazy(() =>
    importRenderer().then((m) => ({ default: m.MarkdownRenderer }))
);

let preloadStarted = false;
/** Warm the markdown-renderer chunk (call on idle so it's ready before first use). */
export function preloadMarkdownRenderer(): void {
    if (preloadStarted) return;
    preloadStarted = true;
    void importRenderer();
}

/** Raw-text fallback shown for the brief moment the renderer chunk is loading. */
function PlainTextFallback({ content, className, cursor }: MarkdownRendererProps) {
    return (
        <div className={cn('whitespace-pre-wrap break-words', className)}>
            {content}
            {cursor}
        </div>
    );
}

export function MarkdownRenderer(props: MarkdownRendererProps) {
    useEffect(() => {
        preloadMarkdownRenderer();
    }, []);
    return (
        <Suspense fallback={<PlainTextFallback {...props} />}>
            <MarkdownRendererImpl {...props} />
        </Suspense>
    );
}
