// Verifies createWorkflowNode defends against a missing/invalid position, which
// otherwise reaches xyflow's adoptUserNodes and hard-crashes the whole canvas
// ("Cannot read properties of undefined (reading 'x')"). Backend/synced/pasted
// nodes can arrive without a position despite the typed signature.
import { nc } from '~/lib/nc';
import { createWorkflowNode } from '~/lib/applyNodeUpdate';

export default async function () {
    const out: Record<string, unknown> = {};

    // 1. Missing position → repaired to origin, no throw.
    const missing = createWorkflowNode('n1', 'automation-slack', undefined as never, {});
    out.missing = missing.position;
    nc.assert.equal(missing.position?.x, 0, 'missing position.x defaults to 0');
    nc.assert.equal(missing.position?.y, 0, 'missing position.y defaults to 0');

    // 2. NaN/non-finite position → repaired to origin.
    const nan = createWorkflowNode('n2', 'automation-slack', { x: NaN, y: 0 } as never, {});
    out.nan = nan.position;
    nc.assert.equal(nan.position?.x, 0, 'NaN position repaired to origin');

    // 3. Valid position → preserved unchanged.
    const good = createWorkflowNode('n3', 'automation-slack', { x: 123, y: 456 }, {});
    out.good = good.position;
    nc.assert.equal(good.position?.x, 123, 'valid position.x preserved');
    nc.assert.equal(good.position?.y, 456, 'valid position.y preserved');

    // 4. The repaired nodes have a valid shape for xyflow (position.x is a number).
    nc.assert.equal(typeof missing.position?.x, 'number', 'position.x is a number');

    return { ok: true, ...out };
}
