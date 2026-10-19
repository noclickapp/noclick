// Markdown formatting for a plain textarea, the way a chat composer's toolbar
// and shortcuts apply it: wrap the selection in inline marks, prefix its lines
// for lists and quotes, fence it as code, or make it a link. Every function is
// a pure edit (value + selection in, value + selection out), so the rules are
// unit-testable; useTextFormatting applies them to the live textarea.

export type InlineFormat = 'bold' | 'italic' | 'strike' | 'code';
export type LineFormat = 'bulleted' | 'numbered' | 'quote';
export type TextFormat = InlineFormat | LineFormat | 'link' | 'codeBlock';

export interface TextEdit {
    value: string;
    selectionStart: number;
    selectionEnd: number;
}

const MARK: Record<InlineFormat, string> = { bold: '**', italic: '_', strike: '~~', code: '`' };
const LIST_MARKER = /^(\s*)(?:[-*+]|\d+[.)])\s+/;
const BULLET = /^\s*[-*+]\s+/;
const NUMBER = /^\s*\d+[.)]\s+/;
const QUOTE = /^>\s?/;

/** Replace `value[start, end)` with `text`, the caret after it. */
export function insertText(value: string, start: number, end: number, text: string): TextEdit {
    const caret = start + text.length;
    return { value: value.slice(0, start) + text + value.slice(end), selectionStart: caret, selectionEnd: caret };
}

function wrapInline(value: string, start: number, end: number, mark: string): TextEdit {
    const n = mark.length;
    // The selection (or an empty pair around the caret) is already marked: unmark it.
    if (value.slice(start - n, start) === mark && value.slice(end, end + n) === mark) {
        return {
            value: value.slice(0, start - n) + value.slice(start, end) + value.slice(end + n),
            selectionStart: start - n,
            selectionEnd: end - n,
        };
    }
    const selected = value.slice(start, end);
    if (selected.length >= n * 2 && selected.startsWith(mark) && selected.endsWith(mark)) {
        return { value: value.slice(0, start) + selected.slice(n, -n) + value.slice(end), selectionStart: start, selectionEnd: end - n * 2 };
    }
    // Marks hug the words: `**word** ` rather than `**word **`, which markdown ignores.
    if (selected.trim()) {
        start += selected.length - selected.trimStart().length;
        end -= selected.length - selected.trimEnd().length;
    }
    return {
        value: value.slice(0, start) + mark + value.slice(start, end) + mark + value.slice(end),
        selectionStart: start + n,
        selectionEnd: end + n,
    };
}

/** The whole lines a selection touches; a selection ending on a line break stops before it. */
function lineRange(value: string, start: number, end: number): { from: number; to: number } {
    const from = value.lastIndexOf('\n', start - 1) + 1;
    const last = end > start && value[end - 1] === '\n' ? end - 1 : end;
    const to = value.indexOf('\n', last);
    return { from, to: to === -1 ? value.length : to };
}

function prefixLines(value: string, start: number, end: number, format: LineFormat): TextEdit {
    const { from, to } = lineRange(value, start, end);
    const lines = value.slice(from, to).split('\n');
    const has = format === 'quote' ? QUOTE : format === 'bulleted' ? BULLET : NUMBER;
    const filled = lines.filter((line) => line.trim());
    const removing = filled.length > 0 && filled.every((line) => has.test(line));
    let count = 0;
    // Each line splits into its marker and its words; only the marker changes.
    const edits = lines.map((line) => {
        const match = (format === 'quote' ? QUOTE : LIST_MARKER).exec(line);
        const indent = format === 'quote' ? '' : (match?.[1] ?? /^\s*/.exec(line)?.[0] ?? '');
        const head = match?.[0] ?? indent;
        // Blank lines between items stay blank rather than becoming empty bullets.
        const keep = !removing && !line.trim() && lines.length > 1;
        const next = keep || removing ? (keep ? head : indent) : format === 'quote' ? '> ' : `${indent}${format === 'bulleted' ? '-' : `${++count}.`} `;
        return { head, next, words: line.slice(head.length) };
    });
    const replaced = edits.map((e) => e.next + e.words).join('\n');
    // A position inside a line's old marker lands where its words now begin.
    const map = (position: number): number => {
        if (position > to) return position + replaced.length - (to - from);
        let oldAt = from;
        let newAt = from;
        for (const { head, next, words } of edits) {
            const oldLength = head.length + words.length;
            if (position <= oldAt + oldLength) return newAt + Math.max(next.length, position - oldAt - head.length + next.length);
            oldAt += oldLength + 1;
            newAt += next.length + words.length + 1;
        }
        return newAt;
    };
    const selectionStart = map(start);
    return {
        value: value.slice(0, from) + replaced + value.slice(to),
        selectionStart,
        selectionEnd: start === end ? selectionStart : Math.max(selectionStart, map(end)),
    };
}

function fence(value: string, start: number, end: number): TextEdit {
    const before = value.slice(0, start);
    const after = value.slice(end);
    const selected = value.slice(start, end);
    if (before.endsWith('```\n') && after.startsWith('\n```')) {
        const from = start - 4;
        return { value: value.slice(0, from) + selected + value.slice(end + 4), selectionStart: from, selectionEnd: from + selected.length };
    }
    // Fences need lines of their own.
    const open = `${before && !before.endsWith('\n') ? '\n' : ''}\`\`\`\n`;
    const close = `\n\`\`\`${after && !after.startsWith('\n') ? '\n' : ''}`;
    const selectionStart = start + open.length;
    return { value: before + open + selected + close + after, selectionStart, selectionEnd: selectionStart + selected.length };
}

function link(value: string, start: number, end: number): TextEdit {
    const selected = value.slice(start, end);
    // A selected URL becomes the link, its label selected to retype; any other
    // text becomes the label, the URL placeholder selected to paste over.
    const [text, selectFrom, selectLength] = /^https?:\/\/\S+$/.test(selected)
        ? [`[${selected}](${selected})`, 1, selected.length]
        : selected
          ? [`[${selected}](url)`, selected.length + 3, 3]
          : ['[text](url)', 1, 4];
    return {
        value: value.slice(0, start) + text + value.slice(end),
        selectionStart: start + selectFrom,
        selectionEnd: start + selectFrom + selectLength,
    };
}

/** Apply one toolbar format to the selection `[start, end)`. Applying it again undoes it. */
export function applyFormat(value: string, start: number, end: number, format: TextFormat): TextEdit {
    switch (format) {
        case 'bold':
        case 'italic':
        case 'strike':
        case 'code':
            return wrapInline(value, start, end, MARK[format]);
        case 'bulleted':
        case 'numbered':
        case 'quote':
            return prefixLines(value, start, end, format);
        case 'codeBlock':
            return fence(value, start, end);
        case 'link':
            return link(value, start, end);
    }
}

/**
 * A new line inside a list or quote continues it (the next number, the same
 * bullet); a new line on an empty item ends the list instead. Null when the
 * caret's line is neither, so the plain newline stands.
 */
export function continueList(value: string, caret: number): TextEdit | null {
    const from = value.lastIndexOf('\n', caret - 1) + 1;
    const match = /^(\s*)([-*+]|(\d+)[.)]|>)(\s+)(.*)$/.exec(value.slice(from, caret));
    if (!match) return null;
    const [, indent, marker, num, space, rest] = match;
    const lineEnd = value.indexOf('\n', caret);
    if (!rest.trim() && !value.slice(caret, lineEnd === -1 ? value.length : lineEnd).trim()) {
        return { value: value.slice(0, from) + value.slice(caret), selectionStart: from, selectionEnd: from };
    }
    const nextMarker = num ? `${Number(num) + 1}${marker.slice(num.length)}` : marker;
    return insertText(value, caret, caret, `\n${indent}${nextMarker}${space}`);
}

interface ShortcutKey {
    key: string;
    code: string;
    metaKey: boolean;
    ctrlKey: boolean;
    shiftKey: boolean;
    altKey: boolean;
}

/** The format a keyboard shortcut asks for: ⌘B, ⌘I, ⌘E, ⌘⇧X, ⌘⇧U, ⌘⇧7/8/9. Never ⌘K, the palette's. */
export function formatForShortcut(e: ShortcutKey): TextFormat | null {
    if (!(e.metaKey || e.ctrlKey) || e.altKey) return null;
    const key = e.key.toLowerCase();
    if (!e.shiftKey) return key === 'b' ? 'bold' : key === 'i' ? 'italic' : key === 'e' ? 'code' : null;
    if (key === 'x') return 'strike';
    if (key === 'u') return 'link';
    // Shifted digits read as symbols in `key`; the physical key is stable.
    return e.code === 'Digit7' ? 'numbered' : e.code === 'Digit8' ? 'bulleted' : e.code === 'Digit9' ? 'quote' : null;
}
