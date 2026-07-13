/**
 * E2E repro (part A: warm-session phases) for the "deleted nodes keep coming
 * back" bug: the IndexedDB instant-render cache went stale after deletes and
 * got union-merged back over the authoritative workflow:get response, then
 * re-saved. Drives the real UI (open card → add → save → delete → back →
 * reopen with a poisoned cache) against an existing empty "Untitled"
 * workflow (adopted as scratch; left empty as found). Leaves the cache
 * poisoned + the workflow id in localStorage for the cold-load part
 * (stale-cache-resurrection-coldload.test.ts, run after a real page reload).
 * Uses only window-singleton harness state — no app-module imports, which
 * can resolve to different Vite module instances than the running app.
 */
import { nc } from '~/lib/nc';
import { valtioCache } from '~/lib/indexeddb';

const ZOMBIE = 'zombie_node_e2e';
export const WF_ID_LS_KEY = '__staleCacheResurrectionWfId';

async function serverNodeIds(wfId: string): Promise<string[]> {
    const resp: any = await nc.send({
        event_name: 'workflow:get',
        request_id: crypto.randomUUID(),
        workflow_id: wfId,
    });
    if (resp?.error) throw new Error(`workflow:get failed: ${resp.error}`);
    return (resp?.workflow?.workflow_data?.nodes ?? []).map((n: any) => n.id);
}

/** Click a "0 nodes … Untitled" card until a canvas mounts — for the
 *  workflow with `targetId` when given (several cards can match the text),
 *  else whichever mounts first. */
async function openScratchCard(targetId?: string): Promise<void> {
    const tried = new Set<Element>();
    for (let attempt = 0; attempt < 4; attempt++) {
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
        await nc.wait.until(() => !!nc.nodes.workflowId(), 15000);
        if (!targetId || nc.nodes.workflowId() === targetId) return;
        await goBackToBrowser();
    }
    throw new Error(`no scratch card mounted workflow ${targetId}`);
}

async function goBackToBrowser() {
    window.dispatchEvent(new CustomEvent('noclick:workflow-browser-reset'));
    // The back handler clears the ?workflow param in a deferred navigate();
    // re-opening before it lands leaves WorkflowBrowser's
    // pendingBackNavigation latch set and the next open is ignored.
    await nc.wait.until(
        () =>
            nc.nodes.workflowId() === null &&
            !new URLSearchParams(location.search).get('workflow'),
        10000
    );
}

export default async function () {
    const results: Record<string, unknown> = {};

    // ── Phase 1: create a blank workflow via the real UI button (this also
    // mounts FlowCanvas, which registers the harness socket sender), then
    // add a node and let the autosave land. ──
    const newBtn = Array.from(document.querySelectorAll('button')).find(
        (b) => b.textContent?.trim() === 'New Workflow'
    ) as HTMLElement | undefined;
    if (!newBtn) throw new Error('New Workflow button not found');
    newBtn.click();
    await nc.wait.until(() => !!nc.nodes.workflowId(), 20000);
    const wfId = nc.nodes.workflowId()!;
    localStorage.setItem(WF_ID_LS_KEY, wfId);
    const cacheKey = `workflow-canvas:${wfId}`;
    results.workflowId = wfId;
    // Let workflow:get resolve (localhost RTT is short; the server-poll
    // below is the hard gate for the save actually landing).
    await new Promise((r) => setTimeout(r, 1500));
    if ((await serverNodeIds(wfId)).length !== 0) {
        throw new Error('created scratch workflow is not empty on the server');
    }

    nc.nodes.add(ZOMBIE, 'automation-slack', {}, { x: 200, y: 200 });
    await nc.wait.until(
        async () => (await serverNodeIds(wfId)).includes(ZOMBIE),
        15000,
        400
    );
    // Fix 1: the debounced save must mirror itself into the cache.
    await nc.wait.until(async () => {
        const cached: any = await valtioCache.get(cacheKey);
        return (cached?.nodes ?? []).some((n: any) => n.id === ZOMBIE);
    }, 5000, 300);
    results.cacheMirroredAdd = true;
    // Snapshot the pre-delete cache payload — this is the poison.
    const poison = JSON.parse(
        JSON.stringify(await valtioCache.get(cacheKey))
    );

    // ── Phase 2: delete the node, immediately go back (unmount flush) ──
    nc.nodes.delete(ZOMBIE);
    await nc.wait.until(
        () => !nc.nodes.list().some((n: any) => n.id === ZOMBIE),
        5000
    );
    await goBackToBrowser();
    await nc.wait.until(
        async () => (await serverNodeIds(wfId)).length === 0,
        10000,
        400
    );
    results.deletePersistedOnUnmount = true;
    await nc.wait.until(async () => {
        const cached: any = await valtioCache.get(cacheKey);
        return (cached?.nodes ?? []).length === 0;
    }, 5000, 300);
    results.cacheMirroredDelete = true;

    // ── Phase 3: same-session remount with a poisoned (stale) cache ──
    await valtioCache.set(cacheKey, poison);
    await openScratchCard(wfId);
    // Give the async cache restore + load + a full autosave window time to act.
    await new Promise((r) => setTimeout(r, 3500));
    results.remountNodeIds = nc.nodes.list().map((n: any) => n.id);
    nc.assert.falsy(
        (results.remountNodeIds as string[]).includes(ZOMBIE),
        'same-session remount must not resurrect the deleted node'
    );
    nc.assert.equal(
        (await serverNodeIds(wfId)).length,
        0,
        'server must stay empty after remount with poisoned cache'
    );
    await goBackToBrowser();

    // Leave a poisoned cache behind for the cold-load part (run after a real
    // page reload): the unmount flush above rewrote the cache clean, so
    // poison it again now that no canvas is mounted.
    await valtioCache.set(cacheKey, poison);
    results.poisonLeftForColdLoad = true;
    return results;
}
