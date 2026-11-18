import type { ReactNode } from 'react';
import { cn } from '@/ui/utils';
import { snippetTabs, type Snippet } from '@/screens/console/lib/snippets';
import { CodeSnippet } from './CodeSnippet';

/** A code-first empty state: what's missing, then the call that fills it. */
export function EmptyCode({ title, hint, snippet, children, className }: { title: string; hint?: ReactNode; snippet: Snippet; children?: ReactNode; className?: string }) {
    return (
        <div className={cn('mx-auto flex max-w-2xl flex-col gap-3 px-1 py-8', className)}>
            <div>
                <p className="m-0 text-sm text-foreground">{title}</p>
                {hint && <p className="m-0 mt-1 text-[13px] text-muted-foreground">{hint}</p>}
            </div>
            <CodeSnippet tabs={snippetTabs(snippet)} />
            {children}
        </div>
    );
}
