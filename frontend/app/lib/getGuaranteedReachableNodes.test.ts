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

// Tests for runScopeForRoots' upstream data-provider backfill — the FE mirror
// of the backend's _get_reachable_nodes Phase 2. An unpicked entry path must
// not sever an interface value store (form) or state manager that feeds a
// picked path (2026-07-31 "No data for node" bug).
import { runScopeForRoots } from './getGuaranteedReachableNodes';

const n = (id: string, type: string) => ({ id, type });

describe('runScopeForRoots data-provider backfill', () => {
  const edges = [e('form', 'fn'), e('run', 'fn')];
  const nodes = [n('form', 'interface-form'), n('run', 'trigger-run'), n('fn', 'automation-serverless-function')];

  it('backfills an upstream form store when only the other entry path is picked', () => {
    expect(runScopeForRoots(edges, ['run'], nodes)).toEqual(new Set(['run', 'fn', 'form']));
  });

  it('resolves legacy node types through the alias map', () => {
    const legacy = [n('form', 'interface-config-form'), n('run', 'trigger-run'), n('fn', 'automation-serverless-function')];
    expect(runScopeForRoots(edges, ['run'], legacy)).toEqual(new Set(['run', 'fn', 'form']));
  });

  it('does not backfill ordinary automation predecessors', () => {
    const plain = [n('form', 'automation-slack'), n('run', 'trigger-run'), n('fn', 'automation-serverless-function')];
    expect(runScopeForRoots(edges, ['run'], plain)).toEqual(new Set(['run', 'fn']));
  });

  it('keeps forward-only behavior when nodes are not provided', () => {
    expect(runScopeForRoots(edges, ['run'])).toEqual(new Set(['run', 'fn']));
  });

  it('backfills transitively through chained providers, without pulling their other descendants', () => {
    const chainEdges = [e('store', 'form'), e('form', 'fn'), e('run', 'fn'), e('form', 'other')];
    const chainNodes = [
      n('store', 'state-manager'), n('form', 'interface-form'),
      n('run', 'trigger-run'), n('fn', 'automation-serverless-function'), n('other', 'automation-slack'),
    ];
    expect(runScopeForRoots(chainEdges, ['run'], chainNodes)).toEqual(new Set(['run', 'fn', 'form', 'store']));
  });
});
