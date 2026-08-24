// Pure @-mention token detection for the chat composer. Given the textarea's
// current value and caret offset, finds an active `@file` token the user is
// typing so the composer can show a file autocomplete. Kept separate from the
// component so the boundary rules are unit-testable.

export interface MentionToken {
  /** Index of the `@` in `value`. */
  start: number;
  /** Text between `@` and the caret (the fuzzy query; may be empty). */
  query: string;
}

/**
 * Detect an active mention token ending at `caret`. A token is active when the
 * last `@` before the caret sits at a word boundary (start of input or preceded
 * by whitespace) with no whitespace between it and the caret. Returns null when
 * there is no active token (e.g. mid-word `a@b`, or whitespace after `@`).
 */
export function detectMentionToken(value: string, caret: number): MentionToken | null {
  for (let i = caret - 1; i >= 0; i--) {
    const ch = value[i];
    if (ch === '@') {
      const before = i === 0 ? '' : value[i - 1];
      if (i === 0 || /\s/.test(before)) {
        const query = value.slice(i + 1, caret);
        if (!/\s/.test(query)) return { start: i, query };
      }
      return null;
    }
    // Hit whitespace before finding an `@` → the caret isn't inside a token.
    if (/\s/.test(ch)) return null;
  }
  return null;
}

/**
 * Replace the active `@query` span (from `token.start` to `caret`) with `insert`
 * plus a trailing space. Returns the new value and the caret offset to restore
 * after it.
 */
export function applyMention(
  value: string,
  caret: number,
  token: MentionToken,
  insert: string,
): { value: string; caret: number } {
  const replacement = `${insert} `;
  const nextValue = value.slice(0, token.start) + replacement + value.slice(caret);
  return { value: nextValue, caret: token.start + replacement.length };
}
