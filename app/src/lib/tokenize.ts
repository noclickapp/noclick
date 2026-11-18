// Shiki's tokens as role-tagged runs: the one tokenizer a page's server and the
// browser (loaded the first time a snippet shows) share. The theme maps scopes
// to roles, not colours: each role has a sentinel colour here, and each surface
// owns the real ones (its stylesheet's role classes, the `--code-*` tokens).
// Calls, names and keyword arguments stay plain.
import { createHighlighterCore, type HighlighterCore, type LanguageInput, type ThemeRegistration } from 'shiki/core';
import { createJavaScriptRegexEngine } from 'shiki/engine/javascript';
import { ROLE_CLASSES, type Runs } from '@/lib/highlight';

export const ROLE = { plain: 0, keyword: 1, storage: 2, string: 3, number: 4, comment: 5, type: 6 } as const;
const sentinel = (role: number) => `#0000${role.toString(16).padStart(2, '0')}`;
const ROLE_OF = new Map(ROLE_CLASSES.map((_, role) => [sentinel(role), role]));

const THEME: ThemeRegistration = {
    name: 'noclick-roles',
    type: 'dark',
    colors: { 'editor.foreground': sentinel(ROLE.plain), 'editor.background': sentinel(ROLE.plain) },
    tokenColors: [
        { settings: { foreground: sentinel(ROLE.plain) } },
        { scope: ['comment', 'punctuation.definition.comment'], settings: { foreground: sentinel(ROLE.comment) } },
        { scope: ['keyword.control', 'keyword.operator.logical'], settings: { foreground: sentinel(ROLE.keyword) } },
        {
            scope: ['storage', 'keyword.operator.new', 'constant.language', 'variable.language', 'constant.character.format.placeholder', 'meta.fstring.python punctuation.definition'],
            settings: { foreground: sentinel(ROLE.storage) },
        },
        { scope: ['string', 'punctuation.definition.string'], settings: { foreground: sentinel(ROLE.string) } },
        { scope: ['constant.numeric'], settings: { foreground: sentinel(ROLE.number) } },
        { scope: ['entity.name.type', 'entity.name.class', 'support.class', 'support.type'], settings: { foreground: sentinel(ROLE.type) } },
        // JSON keys read as structure, not types; a shell command's bare words are just words.
        { scope: ['support.type.property-name', 'string.unquoted.argument'], settings: { foreground: sentinel(ROLE.plain) } },
    ],
};

/** A highlighter with the role theme and the given grammars, on the JavaScript regex engine (no WebAssembly). */
export function createRoleHighlighter(langs: LanguageInput[]): Promise<HighlighterCore> {
    return createHighlighterCore({ themes: [THEME], langs, engine: createJavaScriptRegexEngine() });
}

const NAME = /\b[A-Z]\w*\b/g;

/** One block as runs (role, text, role, text, …); `typeNames` (the SDK's classes) colour as types wherever they're plain. */
/**
 * `context`: text the block reads inside (a class body around a member's signature), coloured with it so the
 * grammar sees what the block is, then left out of the runs.
 */
export function tokenize(shiki: HighlighterCore, language: string, code: string, typeNames?: ReadonlySet<string>, context?: { before: string; after: string }): Runs {
    const full = context ? `${context.before}${code}${context.after}` : code;
    let text = '';
    let roles: number[] = [];
    shiki.codeToTokensBase(full, { lang: language, theme: THEME.name }).forEach((line, i) => {
        if (i) {
            text += '\n';
            roles.push(ROLE.plain);
        }
        for (const token of line) {
            const role = ROLE_OF.get((token.color ?? '').toLowerCase());
            if (role === undefined) throw new Error(`Shiki gave a colour the role theme doesn't define: ${token.color}`);
            text += token.content;
            for (let k = 0; k < token.content.length; k++) roles.push(role);
        }
    });
    if (text !== full) throw new Error(`Shiki's tokens don't spell the ${language} block back`);
    if (context) {
        text = code;
        roles = roles.slice(context.before.length, context.before.length + code.length);
    }
    if (typeNames) {
        for (const match of text.matchAll(NAME)) {
            if (!typeNames.has(match[0])) continue;
            for (let k = match.index; k < match.index + match[0].length; k++) if (roles[k] === ROLE.plain) roles[k] = ROLE.type;
        }
    }
    const runs: Runs = [];
    for (let k = 0; k < text.length; k++) {
        if (k && roles[k] === roles[k - 1]) runs[runs.length - 1] += text[k];
        else runs.push(roles[k], text[k]);
    }
    return runs;
}
