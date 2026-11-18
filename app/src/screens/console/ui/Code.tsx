// Coloured code for the console's snippets and JSON: the docs' tokenizer, loaded
// on first use, painted with the theme's `--code-*` tokens so light and dark
// each have their own. Until it loads (or for a language it doesn't colour) the
// code shows plain; the text is the same either way, so copying is unchanged.
import { useEffect, useState } from 'react';
import type { Runs } from '@/lib/highlight';
import type { ConsoleLanguage } from '@/screens/console/lib/highlightCode';

/** Role (as the tokenizer numbers them) → its colour token. */
export const ROLE_COLORS = [
    '',
    'text-[hsl(var(--code-keyword))]',
    'text-[hsl(var(--code-variable))]',
    'text-[hsl(var(--code-string))]',
    'text-[hsl(var(--code-number))]',
    'italic text-[hsl(var(--code-comment))]',
    'text-[hsl(var(--code-function))]',
] as const;

/** A tab's language by its id, where the id names one (`env` is a shell line, `cursor` its JSON config). */
const TAB_LANGUAGES: Record<string, ConsoleLanguage> = {
    python: 'python',
    typescript: 'typescript',
    ts: 'typescript',
    env: 'bash',
    bash: 'bash',
    shell: 'bash',
    curl: 'bash',
    'claude-code': 'bash',
    cursor: 'json',
    json: 'json',
};

export function languageOf(id: string | undefined): ConsoleLanguage | undefined {
    return id ? TAB_LANGUAGES[id] : undefined;
}

/** The block's runs once the tokenizer has loaded, else null. */
export function useCodeRuns(language: ConsoleLanguage | undefined, code: string): Runs | null {
    const key = language ? `${language}\n${code}` : null;
    const [done, setDone] = useState<{ key: string; runs: Runs } | null>(null);
    useEffect(() => {
        if (!language || !key) return;
        let live = true;
        import('@/screens/console/lib/highlightCode')
            .then((m) => m.highlightCode(language, code))
            .then((runs) => {
                if (live) setDone({ key, runs });
            })
            .catch((err: unknown) => console.error('Colouring a code block failed', err));
        return () => {
            live = false;
        };
    }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
    return done && done.key === key ? done.runs : null;
}

/** The text, coloured when its runs have loaded. */
export function CodeText({ code, language }: { code: string; language: ConsoleLanguage | undefined }) {
    const runs = useCodeRuns(language, code);
    if (!runs) return <code>{code}</code>;
    const parts = [];
    for (let i = 0; i < runs.length; i += 2) {
        const role = runs[i] as number;
        const text = runs[i + 1] as string;
        parts.push(
            role ? (
                <span key={i} className={ROLE_COLORS[role]}>
                    {text}
                </span>
            ) : (
                text
            )
        );
    }
    return <code data-highlighted="">{parts}</code>;
}
