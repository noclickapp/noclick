// Code colouring a page's server and the page share: the server tokenizes every
// block on the page and sends role-tagged runs keyed by a hash of the block; the
// page draws them with a class per role.

/** One block's colouring: role, text, role, text, ... (role 0 is plain text). */
export type Runs = (number | string)[];

/** A page's blocks by `codeKey`. */
export type Highlights = Record<string, Runs>;

/** Role -> the class a page colours it with. Most text stays plain; only these carry colour. */
export const ROLE_CLASSES = ['', 'hl-keyword', 'hl-storage', 'hl-string', 'hl-number', 'hl-comment', 'hl-type'] as const;

const ALIASES: Record<string, string> = { py: 'python', sh: 'bash', shell: 'bash', console: 'bash', ts: 'typescript', js: 'typescript', javascript: 'typescript', jsx: 'tsx' };

/** The languages the docs colour; anything else renders as plain text. */
export const DOCS_LANGUAGES = ['python', 'bash', 'json', 'http', 'typescript', 'tsx'] as const;
const KNOWN = new Set<string>(DOCS_LANGUAGES);

export function docsLanguage(language: string | null | undefined): string | undefined {
    const lang = language ? (ALIASES[language] ?? language) : undefined;
    return lang && KNOWN.has(lang) ? lang : undefined;
}

/** A block's key (FNV-1a over language and code), so the page never ships the code twice. */
export function codeKey(language: string, code: string): string {
    let hash = 0x811c9dc5;
    const text = `${language}\n${code}`;
    for (let i = 0; i < text.length; i++) {
        hash ^= text.charCodeAt(i);
        hash = Math.imul(hash, 0x01000193);
    }
    return `${(hash >>> 0).toString(36)}.${text.length.toString(36)}`;
}
