// A git patch read into hunks: the file header dropped, each line numbered on the side it exists on, a hunk's
// section name kept, and git's no-newline marker kept as a note.
import { describe, expect, it } from 'vitest';
import { parseUnifiedDiff } from '~/lib/unifiedDiff';

const PATCH = [
    'diff --git a/src/app.ts b/src/app.ts',
    'index 1a2b3c4..5d6e7f8 100644',
    '--- a/src/app.ts',
    '+++ b/src/app.ts',
    '@@ -1,3 +1,4 @@ export function app() {',
    ' const a = 1;',
    '-const b = 2;',
    '+const b = 3;',
    '+const c = 4;',
    ' return a;',
    '@@ -10 +11 @@',
    '-old',
    '\\ No newline at end of file',
    '+new',
    '',
].join('\n');

describe('parseUnifiedDiff', () => {
    it('numbers each line on the side it exists on, hunk by hunk', () => {
        const [first, second] = parseUnifiedDiff(PATCH);
        expect(first.section).toBe('export function app() {');
        expect(first.lines.map((l) => [l.kind, l.old, l.new, l.text])).toEqual([
            ['ctx', 1, 1, 'const a = 1;'],
            ['del', 2, null, 'const b = 2;'],
            ['add', null, 2, 'const b = 3;'],
            ['add', null, 3, 'const c = 4;'],
            ['ctx', 3, 4, 'return a;'],
        ]);
        expect([second.oldStart, second.newStart, second.section]).toEqual([10, 11, '']);
        expect(second.lines.map((l) => [l.kind, l.text])).toEqual([
            ['del', 'old'],
            ['note', 'No newline at end of file'],
            ['add', 'new'],
        ]);
    });

    it('reads nothing from a patch with no hunks (a mode change, an empty file)', () => {
        expect(parseUnifiedDiff('diff --git a/x b/x\nnew file mode 100644\n')).toEqual([]);
    });
});
