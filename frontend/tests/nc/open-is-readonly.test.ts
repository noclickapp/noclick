/**
 * E2E for the no-op-save content gate: opening a workflow and letting the
 * post-load merge churn through the dirty-marking effect must NOT write the
 * DB (graph_version and updated_at stay put). Before the gate, every open
 * fired a full workflow:update 2s in, bumping updated_at (recency churn)
 * and widening the concurrent-clobber window. Creates and deletes its own
 * scratch workflow.
 */
import { nc } from '~/lib/nc';

async function serverMeta(
    wfId: string
): Promise<{ version: number; updatedAt: string }> {
    const resp: any = await nc.send({
        event_name: 'workflow:get',
        request_id: crypto.randomUUID(),
        workflow_id: wfId,
    });
    if (resp?.error) throw new Error(`workflow:get failed: ${resp.error}`);
    return {
        version: resp?.workflow?.graph_version,
        updatedAt: resp?.workflow?.updated_at,
    };
}

async function goBack() {
    window.dispatchEvent(new CustomEvent('noclick:workflow-browser-reset'));
    await nc.wait.until(
        () =>
            nc.nodes.workflowId() === null &&
            !new URLSearchParams(location.search).get('workflow'),
        10000
    );
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
        // Real content + an acked save, so the baseline reflects a
        // representative graph rather than the empty blank.
        nc.nodes.add('n1', 'automation-slack', {}, { x: 100, y: 100 });
        await nc.wait.until(
            async () => {
                const resp: any = await nc.send({
                    event_name: 'workflow:get',
                    request_id: crypto.randomUUID(),
                    workflow_id: wfId,
                });
                return (
                    (resp?.workflow?.workflow_data?.nodes ?? []).length === 1
                );
            },
            15000,
            400
        );
        await goBack();
        const before = await serverMeta(wfId);
        results.versionBefore = before.version;

        // Reopen and give it a full load + two autosave windows.
        let card: HTMLElement | null = null;
        await nc.wait.until(() => {
            card =
                (Array.from(
                    document.querySelectorAll('[data-workflow-card]')
                ).find((el) =>
                    el.textContent?.includes('Untitled')
                ) as HTMLElement) ?? null;
            return !!card;
        }, 15000);
        card!.click();
        await nc.wait.until(() => nc.nodes.workflowId() === wfId, 15000);
        await new Promise((r) => setTimeout(r, 5000));

        const after = await serverMeta(wfId);
        results.versionAfter = after.version;
        results.updatedAtStable = after.updatedAt === before.updatedAt;
        nc.assert.equal(
            after.version,
            before.version,
            'opening a workflow must not bump graph_version'
        );
        nc.assert.truthy(
            results.updatedAtStable,
            'opening a workflow must not bump updated_at'
        );
        return results;
    } finally {
        await goBack().catch(() => {});
        await nc.send({
            event_name: 'workflow:delete',
            request_id: crypto.randomUUID(),
            workflow_id: wfId,
        });
    }
}
