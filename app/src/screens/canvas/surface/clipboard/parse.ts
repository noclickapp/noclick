// What text on the clipboard (or in a file) stands for, as steps: the canvas's own format first, then whatever else a
// host reads (`canvas.clipboard`'s formats: a link, a command, another tool's export), highest priority first.
import { standing } from '@/slots';
import { CLIPBOARD } from '../../slots';
import { noClickParser } from './noclickFormat';
import type { ClipboardParseResult, ClipboardParser } from './types';

export type { ClipboardParseResult, ClipboardParser, InterfaceLayoutItem } from './types';

/** The formats read, in the order they're tried (a stable sort: equal priorities keep the order they were given in). */
function formats(): ClipboardParser[] {
    return [noClickParser, ...standing(CLIPBOARD).formats].sort((a, b) => b.priority - a.priority);
}

/** The steps and connections `text` stands for in the first format that reads it; null when none does. */
export function parseClipboardContent(text: string): ClipboardParseResult | null {
    if (!text || !text.trim()) return null;
    for (const format of formats()) {
        const result = format.parse(text);
        if (result) return result;
    }
    return null;
}

/** The names of the formats read, in the order they're tried. */
export function getRegisteredParserNames(): string[] {
    return formats().map((format) => format.name);
}
