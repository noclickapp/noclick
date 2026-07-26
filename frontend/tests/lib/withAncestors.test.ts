// Tests for the backward graph closure used to gate "run from here".
//
// The bug it exists for: the gate checked the node plus its DOWNSTREAM, but a
// run whose downstream references upstream data goes out with
// forward_only=false and the backend executes the ancestors too. So clicking
// "Run from here" on a well-configured node happily started a run containing a
// broken upstream one — which read as the gate being ignored entirely.

import { describe, expect, it } from 'vitest';

import { withAncestors } from '~/lib/getGuaranteedReachableNodes';

const edge = (source: string, target: string) => ({ source, target });

describe('withAncestors', () => {
    it('includes the ids themselves', () => {
        expect([...withAncestors([], ['a'])]).toEqual(['a']);
    });

    it('walks back through a chain, not just one hop', () => {
        // a → b → c. Asking for c must pull in b AND a: running c needs b's
        // output, which needs a's. One hop would have missed a.
        const edges = [edge('a', 'b'), edge('b', 'c')];
        expect(withAncestors(edges, ['c'])).toEqual(new Set(['a', 'b', 'c']));
    });

    it('does not walk forward', () => {
        // The forward set is the caller's job (getAllDownstreamNodes); if this
        // also went forward the gate would flag unrelated later steps.
        const edges = [edge('a', 'b'), edge('b', 'c')];
        expect(withAncestors(edges, ['a'])).toEqual(new Set(['a']));
    });

    it('merges the ancestry of several starting points', () => {
        const edges = [edge('a', 'c'), edge('b', 'c'), edge('c', 'd'), edge('x', 'y')];
        expect(withAncestors(edges, ['d', 'y'])).toEqual(
            new Set(['a', 'b', 'c', 'd', 'x', 'y'])
        );
    });

    it('terminates on a cycle', () => {
        // Cycles are reachable on a canvas (a loop back into an earlier step),
        // and an unguarded backward BFS would spin forever mid-click.
        const edges = [edge('a', 'b'), edge('b', 'a')];
        expect(withAncestors(edges, ['a'])).toEqual(new Set(['a', 'b']));
    });

    it('handles a diamond without revisiting the shared ancestor', () => {
        const edges = [edge('root', 'l'), edge('root', 'r'), edge('l', 'end'), edge('r', 'end')];
        expect(withAncestors(edges, ['end'])).toEqual(
            new Set(['root', 'l', 'r', 'end'])
        );
    });

    it('is empty for no starting points', () => {
        expect(withAncestors([edge('a', 'b')], [])).toEqual(new Set());
    });
});
