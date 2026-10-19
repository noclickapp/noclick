// The composer's markdown edits: each takes a value and a selection and must
// return the text a person expects to see, with the selection where they'd
// keep typing.
import { describe, expect, it } from 'vitest';
import { applyFormat, continueList, formatForShortcut, insertText, type TextEdit, type TextFormat } from '~/utils/markdownFormat';

/** `[` and `]` mark the selection; a lone `|` marks the caret. */
function parse(marked: string): { value: string; start: number; end: number } {
    const caret = marked.indexOf('|');
    if (caret !== -1) return { value: marked.replace('|', ''), start: caret, end: caret };
    const start = marked.indexOf('[');
    const end = marked.indexOf(']') - 1;
    return { value: marked.replace('[', '').replace(']', ''), start, end };
}

function show(edit: TextEdit): string {
    const { value, selectionStart: s, selectionEnd: e } = edit;
    return s === e ? `${value.slice(0, s)}|${value.slice(s)}` : `${value.slice(0, s)}[${value.slice(s, e)}]${value.slice(e)}`;
}

const format = (marked: string, f: TextFormat) => {
    const { value, start, end } = parse(marked);
    return show(applyFormat(value, start, end, f));
};

describe('inline formats', () => {
    it('wraps the selection and keeps it selected', () => {
        expect(format('ship [today] please', 'bold')).toBe('ship **[today]** please');
        expect(format('ship [today] please', 'italic')).toBe('ship _[today]_ please');
        expect(format('ship [today] please', 'strike')).toBe('ship ~~[today]~~ please');
        expect(format('run [npm test] now', 'code')).toBe('run `[npm test]` now');
    });

    it('applying it again takes it off', () => {
        expect(format('ship **[today]** please', 'bold')).toBe('ship [today] please');
        expect(format('ship [**today**] please', 'bold')).toBe('ship [today] please');
    });

    it('leaves surrounding spaces outside the marks, where markdown needs them', () => {
        expect(format('ship[ today ]please', 'bold')).toBe('ship **[today]** please');
    });

    it('opens an empty pair at the caret, and closes it again', () => {
        expect(format('say |', 'bold')).toBe('say **|**');
        expect(format('say **|**', 'bold')).toBe('say |');
    });
});

describe('line formats', () => {
    it('bullets every selected line', () => {
        expect(format('[one\ntwo]', 'bulleted')).toBe('- [one\n- two]');
    });

    it('numbers lines in order, skipping blank ones', () => {
        expect(format('[one\n\ntwo]', 'numbered')).toBe('1. [one\n\n2. two]');
    });

    it('turns one kind of list into the other', () => {
        expect(format('[- one\n- two]', 'numbered')).toBe('1. [one\n2. two]');
    });

    it('removes the markers when every line already has them', () => {
        expect(format('[- one\n- two]', 'bulleted')).toBe('[one\ntwo]');
        expect(format('> quoted|', 'quote')).toBe('quoted|');
    });

    it('starts a list on an empty line at the caret', () => {
        expect(format('notes\n|', 'bulleted')).toBe('notes\n- |');
    });

    it('works from a caret inside the line', () => {
        expect(format('first li|ne', 'quote')).toBe('> first li|ne');
    });
});

describe('code blocks', () => {
    it('fences the selection on lines of its own', () => {
        expect(format('see [a = 1] here', 'codeBlock')).toBe('see \n```\n[a = 1]\n```\n here');
    });

    it('opens an empty block with the caret inside', () => {
        expect(format('|', 'codeBlock')).toBe('```\n|\n```');
    });

    it('unfences a fenced selection', () => {
        expect(format('```\n[a = 1]\n```', 'codeBlock')).toBe('[a = 1]');
    });
});

describe('links', () => {
    it('makes the selected words the label, the URL ready to paste over', () => {
        expect(format('read [the post] first', 'link')).toBe('read [the post]([url]) first');
    });

    it('keeps a selected URL as the target, its label ready to retype', () => {
        expect(format('[https://noclick.com]', 'link')).toBe('[[https://noclick.com]](https://noclick.com)');
    });

    it('inserts a template when nothing is selected', () => {
        expect(format('|', 'link')).toBe('[[text]](url)');
    });
});

describe('continueList', () => {
    const next = (marked: string) => {
        const { value, start } = parse(marked);
        const edit = continueList(value, start);
        return edit && show(edit);
    };

    it('carries a bullet or the next number to the new line', () => {
        expect(next('- milk|')).toBe('- milk\n- |');
        expect(next('1. milk\n2. eggs|')).toBe('1. milk\n2. eggs\n3. |');
        expect(next('> said|')).toBe('> said\n> |');
    });

    it('ends the list from an empty item', () => {
        expect(next('- milk\n- |')).toBe('- milk\n|');
    });

    it('leaves plain lines alone', () => {
        expect(next('hello|')).toBeNull();
    });
});

describe('formatForShortcut', () => {
    const key = (k: string, extra: Partial<Parameters<typeof formatForShortcut>[0]> = {}) =>
        formatForShortcut({ key: k, code: '', metaKey: true, ctrlKey: false, shiftKey: false, altKey: false, ...extra });

    it('maps the composer shortcuts', () => {
        expect(key('b')).toBe('bold');
        expect(key('i')).toBe('italic');
        expect(key('e')).toBe('code');
        expect(key('X', { shiftKey: true })).toBe('strike');
        expect(key('U', { shiftKey: true })).toBe('link');
        expect(key('&', { shiftKey: true, code: 'Digit7' })).toBe('numbered');
        expect(key('*', { shiftKey: true, code: 'Digit8' })).toBe('bulleted');
        expect(key('(', { shiftKey: true, code: 'Digit9' })).toBe('quote');
    });

    it('never takes ⌘K, or keys without a modifier', () => {
        expect(key('k')).toBeNull();
        expect(key('b', { metaKey: false })).toBeNull();
    });
});

describe('insertText', () => {
    it('replaces the selection and puts the caret after the insert', () => {
        expect(show(insertText('hi there', 3, 8, '👋'))).toBe('hi 👋|');
    });
});
