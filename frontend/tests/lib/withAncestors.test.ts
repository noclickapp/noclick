// Tests for the backward graph closure used to gate "run from here".
//
// The bug it exists for: the gate checked the node plus its DOWNSTREAM, but a
// run whose downstream references upstream data goes out with
// forward_only=false and the backend executes the ancestors too. So clicking
// "Run from here" on a well-configured node happily started a run containing a
// broken upstream one — which read as the gate being ignored entirely.

import { describe, expect, it } from 'vitest';

import {
    withAncestors,
    withWiredToolProviders,
} from '~/lib/getGuaranteedReachableNodes';

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

// ── Tool-provider backfill ─────────────────────────────────────────────────
// A bottom-handle edge points from the provider INTO the agent, so a provider
// is neither downstream of its consumer nor {{ref}}-referenced by it — but the
// backend backfills them so the agent keeps its tools. "Run from here" on an
// agent therefore ran Telegram and Google Forms providers with no actions
// allowlisted, past a gate that could not see them.


const toolEdge = (source: string, target: string) => ({
    source,
    target,
    targetHandle: 'bottom',
});

describe('withWiredToolProviders', () => {
    it('pulls in a provider wired into a node in the set', () => {
        expect(withWiredToolProviders([toolEdge('slack', 'agent')], ['agent'])).toEqual(
            new Set(['agent', 'slack'])
        );
    });

    it('pulls in every provider on the same consumer', () => {
        const edges = [toolEdge('telegram', 'agent'), toolEdge('forms', 'agent')];
        expect(withWiredToolProviders(edges, ['agent'])).toEqual(
            new Set(['agent', 'telegram', 'forms'])
        );
    });

    it('ignores ordinary dataflow edges', () => {
        // Only bottom-handle edges are tool wiring. Treating every incoming
        // edge as one would drag unrelated upstream steps into the gate.
        expect(withWiredToolProviders([edge('a', 'agent')], ['agent'])).toEqual(
            new Set(['agent'])
        );
    });

    it('does not pull in providers of a consumer outside the set', () => {
        const edges = [toolEdge('slack', 'other-agent')];
        expect(withWiredToolProviders(edges, ['agent'])).toEqual(new Set(['agent']));
    });

    it('follows hosting chains to a fixpoint', () => {
        // An MCP node in hosting mode is itself a consumer of bottom-handle
        // providers, so one pass would stop short of the real leaf.
        const edges = [toolEdge('mcp', 'agent'), toolEdge('slack', 'mcp')];
        expect(withWiredToolProviders(edges, ['agent'])).toEqual(
            new Set(['agent', 'mcp', 'slack'])
        );
    });

    it('terminates on a wiring cycle', () => {
        const edges = [toolEdge('a', 'b'), toolEdge('b', 'a')];
        expect(withWiredToolProviders(edges, ['a'])).toEqual(new Set(['a', 'b']));
    });
});
