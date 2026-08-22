// JSON embedded in an inline <script> needs one extra layer beyond
// JSON.stringify: `<` must not be allowed to begin a closing script tag, and
// the two JavaScript line-separator characters must remain escaped. Escaping
// the other HTML-significant characters keeps the generated document inert in
// older parsers as well.
const INLINE_SCRIPT_ESCAPES: Record<string, string> = {
    '<': '\\u003c',
    '>': '\\u003e',
    '&': '\\u0026',
    '\u2028': '\\u2028',
    '\u2029': '\\u2029',
};

export function serializeForInlineScript(value: unknown): string {
    const serialized = JSON.stringify(value);
    if (serialized === undefined) return 'null';
    return serialized.replace(
        /[<>&\u2028\u2029]/g,
        (character) => INLINE_SCRIPT_ESCAPES[character]
    );
}
