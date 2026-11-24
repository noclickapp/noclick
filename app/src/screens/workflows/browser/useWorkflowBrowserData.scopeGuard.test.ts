// @vitest-environment happy-dom
//
// Tests the scope-generation guard + volatile-state reset in useWorkflowBrowserData.
// Added with the org-switch staleness fix (and hardened after review):
//  - A monotonic scope generation is bumped on every valtio_path change; each
//    fetch stamps the generation it was issued under and its callback bails if
//    the generation has moved on — so a workflows / folders response from a
//    superseded scope can't overwrite the current org's state, INCLUDING the
//    A→B→A case a path-string compare couldn't distinguish.
//  - The same scope-change detection resets the org-scoped VOLATILE state
//    (subscriptionTier / hiddenSharedCount / loadingWorkflowsMap) that is plain
//    useState (not scope-keyed), so it doesn't show the previous org's values.

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useWorkflowBrowserData } from './useWorkflowBrowserData';
import { __resetBrowserStoreForTests } from './workflowBrowserStore';
import { installFakeBrowserClient, listing, settle as flush } from './fakeBrowserClient';

let api: ReturnType<typeof installFakeBrowserClient>;

beforeEach(() => {
    __resetBrowserStoreForTests();
    api = installFakeBrowserClient();
});

afterEach(() => api.teardown());

/** The `index`th folder-tree read (never the shared-with-me one). */
function treeRequest(index: number) {
    return api.calls.filter((c) => c.path === '/v1/workflows/folders' && !c.query.shared_with_me)[index];
}

function folder(id: string, name: string) {
    return { object: 'workflow_folder', id, name, description: null, parent_id: null, depth: 0, workflow_count: 0, access: 'owner' };
}

describe('useWorkflowBrowserData — scope-generation guard', () => {
    it('drops a get_tree response from the previous scope after a switch', async () => {
        const { result, rerender } = renderHook(
            ({ path }) => useWorkflowBrowserData(path),
            { initialProps: { path: 'wb/orgA' } },
        );
        await act(async () => { await flush(); });
        const reqA = treeRequest(0);
        expect(reqA.query.organization_id).toBe('wb/orgA');

        await act(async () => { rerender({ path: 'wb/orgB' }); await flush(); });

        await act(async () => {
            reqA.answer(listing([folder('fa', 'A-folder')]));
            await flush();
        });

        expect(result.current.folderTree.some((n) => n.name === 'A-folder')).toBe(false);
    });

    it('still applies an in-scope get_tree response (guard does not over-reject)', async () => {
        const { result } = renderHook(
            ({ path }) => useWorkflowBrowserData(path),
            { initialProps: { path: 'wb/orgC' } },
        );
        await act(async () => { await flush(); });
        const reqC = treeRequest(0);

        await act(async () => {
            reqC.answer(listing([folder('fc', 'C-folder')]));
            await flush();
        });

        expect(result.current.folderTree.some((n) => n.name === 'C-folder')).toBe(true);
    });

    it('drops a stale response across an A→B→A cycle (generation, not path-string)', async () => {
        const { result, rerender } = renderHook(
            ({ path }) => useWorkflowBrowserData(path),
            { initialProps: { path: 'wb/orgA' } },
        );
        await act(async () => { await flush(); });
        const reqA1 = treeRequest(0); // issued in the FIRST A session (gen 0)

        // A → B → A. Returning to the same path string would fool a string compare;
        // the generation has advanced to 2, so reqA1 (gen 0) is still stale.
        await act(async () => { rerender({ path: 'wb/orgB' }); await flush(); });
        await act(async () => { rerender({ path: 'wb/orgA' }); await flush(); });
        const reqA2 = treeRequest(2); // issued in the SECOND A session (gen 2)

        await act(async () => {
            reqA1.answer(listing([folder('a1', 'A1-stale')]));
            await flush();
        });
        expect(result.current.folderTree.some((n) => n.name === 'A1-stale')).toBe(false);

        // The current-generation A response still applies.
        await act(async () => {
            reqA2.answer(listing([folder('a2', 'A2-fresh')]));
            await flush();
        });
        expect(result.current.folderTree.some((n) => n.name === 'A2-fresh')).toBe(true);
    });

    it('resets org-scoped volatile state (tier / hidden count) on scope change', async () => {
        const { result, rerender } = renderHook(
            ({ path }) => useWorkflowBrowserData(path),
            { initialProps: { path: 'wb/orgPaid' } },
        );
        await act(async () => {
            await flush();
            for (const call of api.calls.splice(0)) {
                call.answer(call.path === '/v1/workflows' && !call.query.shared_with_me
                    ? listing([], { plan: 'pro', hidden_shared_count: 5 }) : listing([]));
            }
            await flush();
        });
        // Org A loaded as a paid org at its limit.
        expect(result.current.subscriptionTier).toBe('pro');
        expect(result.current.hiddenSharedCount).toBe(5);

        // Switch to a new org; the new org's fetch stays pending (nothing answers it),
        // so the values must come from the render-time reset, not a refetch.
        await act(async () => { rerender({ path: 'wb/orgFree' }); await Promise.resolve(); });

        expect(result.current.subscriptionTier).toBe('free');
        expect(result.current.hiddenSharedCount).toBe(0);
    });
});
