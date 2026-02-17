// Debug test: verify output history carousel renders for a node with history data.
import { nc } from '~/lib/nc';

export default async function () {
    // Get all nodes
    const nodes = nc.nodes.list();
    const nodesWithOutput = nodes.filter(n => n.data?.output !== undefined && n.data?.output !== null);

    if (nodesWithOutput.length === 0) {
        return { error: 'No nodes with output found', totalNodes: nodes.length };
    }

    // First click a node WITHOUT output to reset prevNodeIdRef
    const nodesWithoutOutput = nodes.filter(n => n.data?.output === undefined || n.data?.output === null);
    if (nodesWithoutOutput.length > 0) {
        const wfId = nc.nodes.workflowId();
        document.dispatchEvent(new CustomEvent('noclick:workflow:select-node', {
            detail: { workflowId: wfId, nodeId: nodesWithoutOutput[0].id }
        }));
        await nc.wait.ms(500);
    }

    // Now select a node WITH output
    const targetNode = nodesWithOutput[0];
    const wfId = nc.nodes.workflowId();
    document.dispatchEvent(new CustomEvent('noclick:workflow:select-node', {
        detail: { workflowId: wfId, nodeId: targetNode.id }
    }));
    await nc.wait.ms(1500);

    // Look for carousel elements
    const tabularNums = Array.from(document.querySelectorAll('.tabular-nums')).map(el => el.textContent);
    const trackingWider = Array.from(document.querySelectorAll('.tracking-wider')).filter(el =>
        el.textContent?.includes('Output')
    ).map(el => el.parentElement?.innerHTML?.substring(0, 500));

    return {
        targetNodeId: targetNode.id,
        totalNodesWithOutput: nodesWithOutput.length,
        tabularNums,
        outputPanelHTML: trackingWider,
    };
}
