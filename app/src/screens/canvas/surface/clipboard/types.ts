// What a paste on the canvas becomes: the steps and connections one of the clipboard's formats reads out of its text.
// The canvas's own format (noclickFormat.ts) is always read; a host adds others (`canvas.clipboard`).
import type { Edge, Node } from '@xyflow/react';

/** One block's place on a page's grid, as a copy carries it beside its step. */
export interface InterfaceLayoutItem {
    i: string;
    x: number;
    y: number;
    w: number;
    h: number;
    minW?: number;
    minH?: number;
}

/** What a format read: steps and connections ready to be added to the canvas, and where the steps that are a page's
 *  blocks sat on its grid. */
export interface ClipboardParseResult {
    nodes: Node[];
    edges: Edge[];
    interface?: { layout: InterfaceLayoutItem[] };
}

/** A format a paste may be in. Formats are tried from the highest `priority` down until one reads the text. */
export interface ClipboardParser {
    /** Its name, for a person debugging a paste. */
    name: string;
    /** 100 for the canvas's own format; lower for the rest. */
    priority: number;
    /** The steps the text stands for; null when the text isn't in this format. */
    parse(text: string): ClipboardParseResult | null;
}
