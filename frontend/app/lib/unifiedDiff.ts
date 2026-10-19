// One file's patch in git's unified format, as hunks of numbered lines a page can draw: the header lines before
// the first hunk (diff --git, index, ---/+++, modes) are dropped, and git's "\ No newline at end of file" is a
// note under the line it belongs to.

export type DiffLineKind = 'add' | 'del' | 'ctx' | 'note';

export interface DiffLine {
    kind: DiffLineKind;
    /** The line without its +, - or space. */
    text: string;
    /** Its number before the commit (deleted and context lines) and after it (added and context lines). */
    old: number | null;
    new: number | null;
}

export interface DiffHunk {
    /** What follows the second @@: the function or section the hunk sits in, when git names one. */
    section: string;
    oldStart: number;
    newStart: number;
    lines: DiffLine[];
}

const HUNK = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@ ?(.*)$/;

export function parseUnifiedDiff(patch: string): DiffHunk[] {
    const hunks: DiffHunk[] = [];
    let hunk: DiffHunk | null = null;
    let oldLine = 0;
    let newLine = 0;
    for (const line of patch.replace(/\n$/, '').split('\n')) {
        const head = HUNK.exec(line);
        if (head) {
            oldLine = Number(head[1]);
            newLine = Number(head[2]);
            hunk = { section: head[3], oldStart: oldLine, newStart: newLine, lines: [] };
            hunks.push(hunk);
            continue;
        }
        if (!hunk) continue;
        const mark = line.charAt(0);
        const text = line.slice(1);
        if (mark === '+') hunk.lines.push({ kind: 'add', text, old: null, new: newLine++ });
        else if (mark === '-') hunk.lines.push({ kind: 'del', text, old: oldLine++, new: null });
        else if (mark === '\\') hunk.lines.push({ kind: 'note', text: line.slice(2), old: null, new: null });
        else hunk.lines.push({ kind: 'ctx', text, old: oldLine++, new: newLine++ });
    }
    return hunks;
}
