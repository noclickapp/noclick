// The console's code colouring: the docs' tokenizer over the few languages the
// console shows. Loaded with `import()` the first time a snippet renders, so
// Shiki stays out of the console's first load.
import type { HighlighterCore } from 'shiki/core';
import bash from 'shiki/langs/bash.mjs';
import json from 'shiki/langs/json.mjs';
import python from 'shiki/langs/python.mjs';
import typescript from 'shiki/langs/typescript.mjs';
import type { Runs } from '@/lib/highlight';
import { createRoleHighlighter, tokenize } from '@/lib/tokenize';

export const CONSOLE_LANGUAGES = ['python', 'typescript', 'bash', 'json'] as const;
export type ConsoleLanguage = (typeof CONSOLE_LANGUAGES)[number];

let highlighter: Promise<HighlighterCore> | null = null;
const cache = new Map<string, Runs>();

/** A block as role-tagged runs; the same text, so copying the source is unchanged. */
export async function highlightCode(language: ConsoleLanguage, code: string): Promise<Runs> {
    const key = `${language}\n${code}`;
    const hit = cache.get(key);
    if (hit) return hit;
    highlighter ??= createRoleHighlighter([python, typescript, bash, json]);
    const runs = tokenize(await highlighter, language, code);
    cache.set(key, runs);
    return runs;
}
