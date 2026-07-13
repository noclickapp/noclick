/**
 * E2E for CAS conflict + rebase on workflow:update. An "external" writer
 * (MCP server, another device — simulated by a raw unconditional
 * workflow:update) bumps graph_version while the canvas holds a stale
 * snapshot; the canvas's next autosave must conflict, rebase the external
 * node in, and re-save — instead of silently clobbering it off the server
 * (the pre-CAS behavior). Creates its own scratch workflow and deletes it.
 */
import { nc } from '~/lib/nc';

async function serverGraph(
    wfId: string
): Promise<{ nodes: any[]; version: number }> {
    const resp: any = await nc.send({
        event_name: 'workflow:get',
        request_id: crypto.randomUUID(),
        workflow_id: wfId,
    });
    if (resp?.error) throw new Error(`workflow:get failed: ${resp.error}`);
    return {
        nodes: resp?.workflow?.workflow_data?.nodes ?? [],
        version: resp?.workflow?.graph_version,
    };
}

export default async function () {
    const results: Record<string, unknown> = {};

    const newBtn = Array.from(document.querySelectorAll('button')).find(
        (b) => b.textContent?.trim() === 'New Workflow'
    ) as HTMLElement | undefined;
    if (!newBtn) throw new Error('New Workflow button not found');
    newBtn.click();
    await nc.wait.until(() => !!nc.nodes.workflowId(), 20000);
    const wfId = nc.nodes.workflowId()!;

    try {
        // Local node, acked save (canvas now holds the current version).
        nc.nodes.add('local_node', 'automation-slack', {}, { x: 100, y: 100 });
        await nc.wait.until(
            async () =>
                (await serverGraph(wfId)).nodes.some(
                    (n: any) => n.id === 'local_node'
                ),
            15000,
            400
        );
        const before = await serverGraph(wfId);
        results.versionBeforeExternalWrite = before.version;

        // External writer: unconditional write (no expected_graph_version),
        // exactly what the MCP server / another device does. Bumps the
        // version server-side; the canvas doesn't know.
        const externalNode = {
            id: 'external_node',
            type: 'automation-gmail',
            position: { x: 400, y: 100 },
            config: {},
        };
        const extResp: any = await nc.send({
            event_name: 'workflow:update',
            request_id: crypto.randomUUID(),
            workflow_id: wfId,
            workflow_data: {
                nodes: [...before.nodes, externalNode],
                edges: [],
            },
        });
        if (extResp?.error) {
            throw new Error(`external write failed: ${extResp.error}`);
        }
        results.versionAfterExternalWrite = extResp?.workflow?.graph_version;

        // Stale-canvas edit → the debounced CAS save must conflict, rebase
        // external_node in, and re-save everything under the new version.
        nc.nodes.add('local_node_2', 'automation-slack', {}, { x: 100, y: 300 });
        await nc.wait.until(
            async () => {
                const g = await serverGraph(wfId);
                const ids = g.nodes.map((n: any) => n.id);
                return (
                    ids.includes('local_node') &&
                    ids.includes('local_node_2') &&
                    ids.includes('external_node')
                );
            },
            20000,
            500
        );
        const after = await serverGraph(wfId);
        results.serverNodeIds = after.nodes.map((n: any) => n.id).sort();
        results.versionAfterRebase = after.version;
        results.canvasNodeIds = nc.nodes
            .list()
            .map((n: any) => n.id)
            .sort();
        nc.assert.truthy(
            (results.canvasNodeIds as string[]).includes('external_node'),
            'rebase must surface the external node on the canvas'
        );
        return results;
    } finally {
        window.dispatchEvent(
            new CustomEvent('noclick:workflow-browser-reset')
        );
        await nc.wait
            .until(
                () => !new URLSearchParams(location.search).get('workflow'),
                10000
            )
            .catch(() => {});
        await nc.send({
            event_name: 'workflow:delete',
            request_id: crypto.randomUUID(),
            workflow_id: wfId,
        });
    }
}
