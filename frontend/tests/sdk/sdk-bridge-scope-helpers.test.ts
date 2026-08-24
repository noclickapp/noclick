// Pure scope-helper tests pin the deny-by-default rules independently of React
// and socket machinery. They cover malformed, collaborator, and wrong-node-type
// inputs so message-shape drift cannot reopen arbitrary node targeting.

import { describe, expect, it } from 'vitest';
import {
  isScopedNodeId,
  requireScopedNode,
  requireScopedNodeIds,
  requireScopedStateNode,
} from '~/lib/sdkBridgeScope';

const nodes = [
  { id: 'http-1', type: 'automation-http-request' },
  { id: 'state-1', type: 'state-manager' },
  { id: 'cursor-1', type: 'collaborator-cursor' },
];

describe('SDK bridge scope helpers', () => {
  it('resolves only ordinary nodes in the current graph', () => {
    expect(requireScopedNode(nodes, 'http-1', 'nodes.getConfig').id).toBe('http-1');
    expect(isScopedNodeId(nodes, 'http-1')).toBe(true);
    expect(isScopedNodeId(nodes, 'cursor-1')).toBe(false);
  });

  it('rejects missing, malformed, unknown, and collaborator IDs', () => {
    for (const candidate of [undefined, '', 42, 'outside', 'cursor-1']) {
      expect(() => requireScopedNode(nodes, candidate, 'nodes.getConfig')).toThrow();
    }
  });

  it('validates every ID in an execution list', () => {
    expect(requireScopedNodeIds(nodes, ['http-1', 'state-1'], 'execution.run', 'runNodes'))
      .toEqual(['http-1', 'state-1']);
    expect(() => requireScopedNodeIds(nodes, ['http-1', 'outside'], 'execution.run', 'runNodes'))
      .toThrow(/outside the current workflow/);
    expect(() => requireScopedNodeIds(nodes, 'http-1', 'execution.run', 'runNodes'))
      .toThrow(/array/);
  });

  it('requires explicit state targets to be state-manager nodes', () => {
    expect(requireScopedStateNode(nodes, 'state-1', 'state.get').id).toBe('state-1');
    expect(() => requireScopedStateNode(nodes, 'http-1', 'state.get'))
      .toThrow(/requires a state-manager node/);
  });
});
