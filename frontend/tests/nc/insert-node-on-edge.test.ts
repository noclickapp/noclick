// Verifies the "insert node on edge" feature: clicking the "+" button on a
// dataflow edge (AnimatedWorkflowEdge) primes useClickToAddNode's insert flow,
// and picking a node from the picker splices it into the edge — dropping the
// original edge and wiring source→new→target.
//
// The test is self-contained: it spins up its own throwaway source/target nodes
// + edge, inserts into that edge, asserts the rewiring, then deletes everything
// through the on-canvas Delete button (which broadcasts removals, so nothing
// lingers on the collab/YJS layer). This keeps it safe to run against any loaded
// workflow without mutating the user's real graph.
import { nc } from '~/lib/nc';

const SRC = '__nc_ins_src';
const TGT = '__nc_ins_tgt';

export default async function () {
  // A valid dataflow node type to use for the throwaway endpoints + the inserted
  // node — borrow one already on canvas, else a common default.
  const dataflowType =
    (nc.nodes.list().find((n: any) => typeof n.type === 'string' && n.type.startsWith('automation-')) as any)?.type
    ?? 'automation-github-rest';

  const created: string[] = [];
  try {
    // Build a fresh source → target edge to insert into. addEdge refuses
    // "dangling" edges, so wait for both endpoints to register first.
    nc.nodes.add(SRC, dataflowType, {}, { x: 80, y: 80 });
    nc.nodes.add(TGT, dataflowType, {}, { x: 520, y: 80 });
    created.push(SRC, TGT);
    await nc.wait.until(() => !!nc.nodes.get(SRC) && !!nc.nodes.get(TGT), 3000);
    nc.nodes.addEdge(SRC, TGT);
    await nc.wait.until(() => nc.nodes.edges().some((e: any) => e.source === SRC && e.target === TGT), 3000);
    const edge = nc.nodes.edges().find((e: any) => e.source === SRC && e.target === TGT);
    nc.assert.truthy(edge, 'setup: source→target edge exists');

    const beforeIds = new Set(nc.nodes.list().map((n: any) => n.id));
    const beforeEdgeCount = nc.nodes.edges().length;

    // 1) edge "+" primes the insert; 2) picker picks a node.
    document.dispatchEvent(new CustomEvent('noclick:insert-node-on-edge', {
      detail: { edgeId: edge!.id, source: SRC, target: TGT, sourceHandle: null, targetHandle: null, position: { x: 300, y: 80 } },
    }));
    document.dispatchEvent(new CustomEvent('noclick:add-connected-node', { detail: { nodeType: dataflowType } }));

    await nc.wait.until(() => nc.nodes.list().some((n: any) => !beforeIds.has(n.id)), 4000);

    const afterNodes = nc.nodes.list();
    const afterEdges = nc.nodes.edges();
    const newNode = afterNodes.find((n: any) => !beforeIds.has(n.id));
    if (newNode) created.push(newNode.id);

    const oldEdgeGone = !afterEdges.some((e: any) => e.id === edge!.id);
    const edgeIn = afterEdges.find((e: any) => e.source === SRC && e.target === newNode!.id);
    const edgeOut = afterEdges.find((e: any) => e.source === newNode!.id && e.target === TGT);

    nc.assert.truthy(newNode, 'a new node was inserted');
    nc.assert.equal(newNode!.type, dataflowType, 'inserted node has the picked type');
    nc.assert.truthy(oldEdgeGone, 'original edge was removed');
    nc.assert.truthy(edgeIn, 'source→new edge was created');
    nc.assert.truthy(edgeOut, 'new→target edge was created');
    nc.assert.equal(edgeIn!.type, 'animated', 'source→new edge is styled');
    nc.assert.equal(edgeOut!.type, 'animated', 'new→target edge is styled');
    nc.assert.equal(afterEdges.length - beforeEdgeCount, 1, 'net +1 edge (drop 1, add 2)');

    return { pass: true, insertedType: dataflowType, spliced: `${SRC} → ${newNode!.id} → ${TGT}` };
  } finally {
    // Tear down via the broadcasting UI delete so nothing lingers on the server.
    for (const id of created) nc.nodes.deleteViaUI(id);
    await nc.wait.ms(80);
  }
}
