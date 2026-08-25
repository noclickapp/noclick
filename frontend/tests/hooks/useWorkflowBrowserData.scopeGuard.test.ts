// @vitest-environment jsdom
//
// Tests the scope-generation guard + volatile-state reset in useWorkflowBrowserData.
// Added with the org-switch staleness fix (and hardened after review):
//  - A monotonic scope generation is bumped on every valtio_path change; each
//    fetch stamps the generation it was issued under and its callback bails if
//    the generation has moved on — so a workflow:list / get_tree response from a
//    superseded scope can't overwrite the current org's state, INCLUDING the
//    A→B→A case a path-string compare couldn't distinguish.
//  - The same scope-change detection resets the org-scoped VOLATILE state
//    (subscriptionTier / hiddenSharedCount / loadingWorkflowsMap) that is plain
//    useState (not scope-keyed), so it doesn't show the previous org's values.

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useWorkflowBrowserData } from '~/hooks/useWorkflowBrowserData';
import { installMockSocket, MockSocket } from '../integration/helpers/mockSocket';
import { __resetBrowserStoreForTests } from '~/lib/workflowBrowserStore';

let socket: MockSocket;
let teardown: (() => void) | null = null;

beforeEach(() => {
    __resetBrowserStoreForTests();
    const installed = installMockSocket();
    socket = installed.socket;
    teardown = installed.teardown;
});

afterEach(() => {
    teardown?.();
    teardown = null;
});

function getTreeRequestId(index: number): string | undefined {
    const evs = socket.sentEvents.filter((e) => e.name === 'workflow_folder:get_tree');
    return (evs[index]?.data as { request_id?: string } | undefined)?.request_id;
}

function folder(id: string, name: string) {
    return { id, name, parent_folder_id: null, workflow_count: 0, is_owner: true, children: [] };
}

async function flush() { await Promise.resolve(); await Promise.resolve(); }

describe('useWorkflowBrowserData — scope-generation guard', () => {
    it('drops a get_tree response from the previous scope after a switch', async () => {
        const { result, rerender } = renderHook(
            ({ path }) => useWorkflowBrowserData(path),
            { initialProps: { path: 'wb/orgA' } },
        );
        await act(async () => { await flush(); });
        const reqA = getTreeRequestId(0);
        expect(reqA).toBeTruthy();

        await act(async () => { rerender({ path: 'wb/orgB' }); await flush(); });

        await act(async () => {
            socket.serverEmit('response', { request_id: reqA, data: { folders: [folder('fa', 'A-folder')] } });
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
        const reqC = getTreeRequestId(0);

        await act(async () => {
            socket.serverEmit('response', { request_id: reqC, data: { folders: [folder('fc', 'C-folder')] } });
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
        const reqA1 = getTreeRequestId(0); // issued in the FIRST A session (gen 0)

        // A → B → A. Returning to the same path string would fool a string compare;
        // the generation has advanced to 2, so reqA1 (gen 0) is still stale.
        await act(async () => { rerender({ path: 'wb/orgB' }); await flush(); });
        await act(async () => { rerender({ path: 'wb/orgA' }); await flush(); });
        const reqA2 = getTreeRequestId(2); // issued in the SECOND A session (gen 2)

        await act(async () => {
            socket.serverEmit('response', { request_id: reqA1, data: { folders: [folder('a1', 'A1-stale')] } });
            await flush();
        });
        expect(result.current.folderTree.some((n) => n.name === 'A1-stale')).toBe(false);

        // The current-generation A response still applies.
        await act(async () => {
            socket.serverEmit('response', { request_id: reqA2, data: { folders: [folder('a2', 'A2-fresh')] } });
            await flush();
        });
        expect(result.current.folderTree.some((n) => n.name === 'A2-fresh')).toBe(true);
    });

    it('resets org-scoped volatile state (tier / hidden count) on scope change', async () => {
        socket.replyTo('workflow_folder:get_tree', { folders: [] });
        socket.replyTo('workflow:list', { workflows: [], subscription_tier: 'pro', hidden_shared_count: 5 });
        socket.replyTo('share:list_shared_with_me', { resources: [] });

        const { result, rerender } = renderHook(
            ({ path }) => useWorkflowBrowserData(path),
            { initialProps: { path: 'wb/orgPaid' } },
        );
        await act(async () => { await flush(); await flush(); });
        // Org A loaded as a paid org at its limit.
        expect(result.current.subscriptionTier).toBe('pro');
        expect(result.current.hiddenSharedCount).toBe(5);

        // Switch to a new org; the new org's fetch stays pending (handlers cleared),
        // so the values must come from the render-time reset, not a refetch.
        socket.clearReplyHandlers();
        await act(async () => { rerender({ path: 'wb/orgFree' }); await Promise.resolve(); });

        expect(result.current.subscriptionTier).toBe('free');
        expect(result.current.hiddenSharedCount).toBe(0);
    });
});
