// Tests for getAllDownstreamNodes — the full forward-reachability used to reset
// stale run-state on every node a fresh run will (re-)execute downstream of a
// start node. Unlike getGuaranteedReachableNodes it must NOT stop at branching
// nodes (either branch might run, so both get cleared) and must exclude the seed.

import { describe, it, expect } from 'vitest';
import { getAllDownstreamNodes, type MinimalEdge } from './getGuaranteedReachableNodes';

const e = (source: string, target: string, sourceHandle?: string): MinimalEdge => ({ source, target, sourceHandle });

describe('getAllDownstreamNodes', () => {
  it('returns all descendants of a linear chain, excluding the seed', () => {
    const edges = [e('a', 'b'), e('b', 'c'), e('c', 'd')];
    expect(getAllDownstreamNodes(edges, 'a')).toEqual(new Set(['b', 'c', 'd']));
    expect(getAllDownstreamNodes(edges, 'c')).toEqual(new Set(['d']));
    expect(getAllDownstreamNodes(edges, 'd')).toEqual(new Set());
  });

  it('follows BOTH branches of a conditional (does not stop at branching)', () => {
    // cond → {x, y}; x → x2. getGuaranteedReachableNodes would stop at `cond`.
    const edges = [e('cond', 'x', 'true'), e('cond', 'y', 'false'), e('x', 'x2')];
    expect(getAllDownstreamNodes(edges, 'cond')).toEqual(new Set(['x', 'y', 'x2']));
  });

  it('does not cross into a disjoint chain', () => {
    const edges = [e('a', 'b'), e('c', 'd')];
    expect(getAllDownstreamNodes(edges, 'a')).toEqual(new Set(['b']));
  });

  it('is cycle-safe and never includes the seed itself', () => {
    const edges = [e('a', 'b'), e('b', 'c'), e('c', 'a')];
    expect(getAllDownstreamNodes(edges, 'a')).toEqual(new Set(['b', 'c']));
  });

  it('handles a diamond (node reachable by two paths counted once)', () => {
    const edges = [e('a', 'b'), e('a', 'c'), e('b', 'd'), e('c', 'd')];
    expect(getAllDownstreamNodes(edges, 'a')).toEqual(new Set(['b', 'c', 'd']));
  });
});
