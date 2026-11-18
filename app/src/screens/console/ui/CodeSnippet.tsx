import { useState } from 'react';
import { cn } from '@/ui/utils';
import type { CodeTab } from '@/screens/console/lib/snippets';
import type { ConsoleLanguage } from '@/screens/console/lib/highlightCode';
import { CodeText, languageOf } from './Code';
import { CopyButton } from './CopyButton';

/** A code block's surface: a faint wash, no border or rule. */
export const CODE_SURFACE = 'min-w-0 overflow-hidden rounded-xl bg-foreground/[0.04] dark:bg-foreground/[0.05]';

/**
 * Mono code on a faint wash, coloured with the theme's code tokens, with copy
 * (always the plain source) and optional language tabs.
 */
export function CodeSnippet({
    code,
    language,
    tabs,
    tab,
    onTabChange,
    className,
}: {
    code?: string;
    /** The language of a lone `code` block; tabs name theirs by id. */
    language?: ConsoleLanguage;
    tabs?: readonly CodeTab[];
    /** Controlled tab id; uncontrolled starts on the first tab. */
    tab?: string;
    onTabChange?: (id: string) => void;
    className?: string;
}) {
    const [own, setOwn] = useState(tabs?.[0]?.id);
    const activeId = tab ?? own;
    const active = tabs?.find((t) => t.id === activeId) ?? tabs?.[0];
    const text = active?.code ?? code ?? '';
    const lang = active ? (active.language ?? languageOf(active.id)) : language;
    if (!tabs) {
        return (
            <div className={cn('relative', CODE_SURFACE, className)}>
                <CopyButton value={text} label="Copy code" className="absolute right-2 top-2" />
                <pre className="m-0 overflow-x-auto py-3 pl-3.5 pr-10 font-mono text-[12px] leading-relaxed text-foreground/90">
                    <CodeText code={text} language={lang} />
                </pre>
            </div>
        );
    }
    return (
        <div className={cn(CODE_SURFACE, className)}>
            <div className="flex items-center justify-between gap-2 px-2 pt-1.5">
                <div role="tablist" className="flex min-w-0 flex-wrap items-center gap-0.5">
                    {tabs.map((t) => (
                        <button
                            key={t.id}
                            type="button"
                            role="tab"
                            aria-selected={t.id === active?.id}
                            onClick={() => {
                                setOwn(t.id);
                                onTabChange?.(t.id);
                            }}
                            className={cn(
                                'h-6 rounded-full px-2.5 text-[12px] font-medium transition-colors',
                                t.id === active?.id ? 'bg-foreground/[0.08] text-foreground' : 'text-foreground/70 hover:text-foreground dark:text-muted-foreground dark:hover:text-foreground'
                            )}
                        >
                            {t.label}
                        </button>
                    ))}
                </div>
                <CopyButton value={text} label="Copy code" />
            </div>
            <pre className="m-0 overflow-x-auto px-3.5 pb-3 pt-2 font-mono text-[12px] leading-relaxed text-foreground/90">
                <CodeText code={text} language={lang} />
            </pre>
        </div>
    );
}
