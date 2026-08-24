// The component SDK is a capability for the workflow graph currently mounted by
// the host. These helpers reject guessed, stale, collaborator-only, or cross-workflow
// node IDs before a bridge call can read, mutate, or execute anything.

export interface BridgeNode {
  id: string;
  type?: string | null;
}

function isBridgeNode(node: BridgeNode): boolean {
  return !!node.id && !!node.type && !node.type.startsWith('collaborator');
}

export function scopedNodeMap(nodes: readonly BridgeNode[]): Map<string, BridgeNode> {
  return new Map(nodes.filter(isBridgeNode).map((node) => [node.id, node]));
}

export function requireScopedNode(
  nodes: readonly BridgeNode[],
  candidate: unknown,
  method: string,
): BridgeNode {
  if (typeof candidate !== 'string' || !candidate) {
    throw new Error(`SDK method ${method} requires a node ID from the current workflow`);
  }
  const node = scopedNodeMap(nodes).get(candidate);
  if (!node) {
    throw new Error(`SDK method ${method} cannot access node outside the current workflow: ${candidate}`);
  }
  return node;
}

export function requireScopedNodeIds(
  nodes: readonly BridgeNode[],
  candidates: unknown,
  method: string,
  field: string,
): string[] {
  if (!Array.isArray(candidates)) {
    throw new Error(`SDK method ${method} requires ${field} to be an array of current-workflow node IDs`);
  }
  return candidates.map((candidate) => requireScopedNode(nodes, candidate, method).id);
}

export function requireScopedStateNode(
  nodes: readonly BridgeNode[],
  candidate: unknown,
  method: string,
): BridgeNode {
  const node = requireScopedNode(nodes, candidate, method);
  if (node.type !== 'state-manager') {
    throw new Error(`SDK method ${method} requires a state-manager node: ${node.id}`);
  }
  return node;
}

export function isScopedNodeId(nodes: readonly BridgeNode[], candidate: unknown): candidate is string {
  return typeof candidate === 'string' && scopedNodeMap(nodes).has(candidate);
}
