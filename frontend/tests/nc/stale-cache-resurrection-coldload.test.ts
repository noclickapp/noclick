/**
 * E2E repro (part B: cold load) for the deleted-node resurrection bug. Run
 * AFTER stale-cache-resurrection.test.ts and a real page reload: the module
 * stores are empty and the IndexedDB cache holds a poisoned (pre-delete)
 * snapshot — the exact state of the original bug report. Opens the workflow
 * and asserts the cache-injected deleted node is dropped after workflow:get
 * instead of union-merged back and re-saved. Leaves the adopted workflow
 * empty and clears the test's localStorage/cache leftovers.
 */
import { nc } from '~/lib/nc';
import { valtioCache } from '~/lib/indexeddb';

const ZOMBIE = 'zombie_node_e2e';
const WF_ID_LS_KEY = '__staleCacheResurrectionWfId';

export default async function () {
    const results: Record<string, unknown> = {};
    const wfId = localStorage.getItem(WF_ID_LS_KEY);
    if (!wfId) throw new Error('part A did not record a workflow id');
    const cacheKey = `workflow-canvas:${wfId}`;

    try {
        const preOpenCache: any = await valtioCache.get(cacheKey);
        results.poisonPresent = (preOpenCache?.nodes ?? []).some(
            (n: any) => n.id === ZOMBIE
        );
        nc.assert.truthy(
            results.poisonPresent,
            'precondition: the poisoned cache must have survived the reload'
        );

        // Open via card click and watch for the transient cache-injected
        // zombie so we know the restore path actually ran. Several cards can
        // read "0 nodes … Untitled" — try each until the adopted id mounts.
        let sawTransientZombie = false;
        const tried = new Set<Element>();
        let mounted = false;
        for (let attempt = 0; attempt < 4 && !mounted; attempt++) {
            let card: HTMLElement | null = null;
            await nc.wait.until(() => {
                card =
                    (Array.from(
                        document.querySelectorAll('[data-workflow-card]')
                    ).find(
                        (el) =>
                            !tried.has(el) &&
                            /(^|[^0-9])0 nodes/.test(el.textContent ?? '') &&
                            el.textContent?.includes('Untitled')
                    ) as HTMLElement) ?? null;
                return !!card;
            }, 15000);
            tried.add(card!);
            card!.click();
            await nc.wait.until(() => {
                if (nc.nodes.list().some((n: any) => n.id === ZOMBIE)) {
                    sawTransientZombie = true;
                }
                return !!nc.nodes.workflowId();
            }, 15000, 30);
            if (nc.nodes.workflowId() === wfId) {
                mounted = true;
            } else {
                window.dispatchEvent(
                    new CustomEvent('noclick:workflow-browser-reset')
                );
                await nc.wait.until(
                    () =>
                        nc.nodes.workflowId() === null &&
                        !new URLSearchParams(location.search).get('workflow'),
                    10000
                );
            }
        }
        if (!mounted) throw new Error('adopted workflow card not found');
        // Load + merge + a full autosave window.
        await nc.wait.until(() => {
            if (nc.nodes.list().some((n: any) => n.id === ZOMBIE)) {
                sawTransientZombie = true;
                return false;
            }
            return true;
        }, 10000, 30);
        await new Promise((r) => setTimeout(r, 3000));
        results.coldLoadRestoreRan = sawTransientZombie;
        results.finalNodeIds = nc.nodes.list().map((n: any) => n.id);
        nc.assert.falsy(
            (results.finalNodeIds as string[]).includes(ZOMBIE),
            'cold load must drop the cache-injected deleted node'
        );
        const resp: any = await nc.send({
            event_name: 'workflow:get',
            request_id: crypto.randomUUID(),
            workflow_id: wfId,
        });
        nc.assert.equal(
            (resp?.workflow?.workflow_data?.nodes ?? []).length,
            0,
            'server must stay empty after cold load with poisoned cache'
        );
        return results;
    } finally {
        // Delete the part-A scratch workflow while the sender is still
        // registered, then drop back to the grid and clear leftovers.
        await nc
            .send({
                event_name: 'workflow:delete',
                request_id: crypto.randomUUID(),
                workflow_id: wfId,
            })
            ?.catch?.(() => {});
        window.dispatchEvent(
            new CustomEvent('noclick:workflow-browser-reset')
        );
        localStorage.removeItem(WF_ID_LS_KEY);
        await valtioCache.delete(cacheKey);
    }
}
