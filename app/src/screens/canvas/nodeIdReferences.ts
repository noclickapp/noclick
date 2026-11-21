// Shared helpers for finding workflow node IDs referenced inside arbitrary code
// strings (e.g. the jsx_source / content of interface-html-react nodes, which
// reference other nodes by bare string ID through the @noclick/sdk rather than
// through canvas edges). Centralizes the substring-matching strategy so the
// CodeMirror node-ID highlighter and the canvas "Used by interface" badge stay
// in sync — if the matching ever moves to a smarter parser, it changes here once.

export interface NodeIdMatch {
  id: string;
  from: number;
  to: number;
}

/** Every occurrence of each node ID inside `code`, as character ranges. */
export function findNodeIdMatches(code: string, nodeIds: Iterable<string>): NodeIdMatch[] {
  const matches: NodeIdMatch[] = [];
  if (!code) return matches;
  for (const id of nodeIds) {
    if (!id) continue;
    let pos = 0;
    while ((pos = code.indexOf(id, pos)) !== -1) {
      matches.push({ id, from: pos, to: pos + id.length });
      pos += id.length;
    }
  }
  return matches;
}

/** Whether `code` references `nodeId` at least once. */
export function codeReferencesNodeId(code: string, nodeId: string): boolean {
  return !!code && !!nodeId && code.includes(nodeId);
}
