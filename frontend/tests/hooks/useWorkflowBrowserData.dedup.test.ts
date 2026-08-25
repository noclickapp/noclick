// @vitest-environment jsdom
//
// Regression test for the duplicate-key bug: share:list_shared_with_me can return
// the same resource under multiple share rows (direct share + shared-folder
// descendant), so sharedWorkflows/sharedFolders arrived with duplicate ids. Those
// flow into the root grid as React keys; duplicate keys corrupt reconciliation,
// which rendered visible duplicate cards AND left stale cards in the DOM across
// org switches (store correct, DOM stale). getWorkflows/getSubfolders (and the
// shared-list setters) now dedup by id so the rendered lists never carry dup keys.

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useWorkflowBrowserData } from '~/hooks/useWorkflowBrowserData';
import { installMockSocket, MockSocket } from '../integration/helpers/mockSocket';
import { __resetBrowserStoreForTests } from '~/lib/workflowBrowserStore';

let socket: MockSocket;
let teardown: (() => void) | null = null;

beforeEach(() => { __resetBrowserStoreForTests(); const i = installMockSocket(); socket = i.socket; teardown = i.teardown; });
afterEach(() => { teardown?.(); teardown = null; });

async function flush() { await Promise.resolve(); await Promise.resolve(); }

// Re-render/settle until `cond(result.current)` holds (the get_tree→workflow:list
// chain is several microtask hops), then return.
async function waitUntil(result: { current: any }, cond: (s: any) => boolean) {
    for (let i = 0; i < 20 && !cond(result.current); i++) {
        await act(async () => { await flush(); });
    }
}

function sharedRes(id: string, name: string, type: 'workflow' | 'workflow_folder') {
    return {
        resource_id: id, resource_type: type, resource_name: name,
        resource_description: '', permission: 'edit',
        shared_by_name: 'Owner', shared_by_email: 'o@x.com', shared_at: '2026-01-01T00:00:00Z',
    };
}

describe('useWorkflowBrowserData — dedup shared resources by id', () => {
    it('drops duplicate ids from share:list so the grid has no duplicate React keys', async () => {
        socket.replyTo('workflow_folder:get_tree', { folders: [] });
        socket.replyTo('workflow:list', { workflows: [] });
        socket.replyTo('share:list_shared_with_me', {
            resources: [
                sharedRes('wf-a', 'Twitter Monitor', 'workflow'),
                sharedRes('wf-a', 'Twitter Monitor', 'workflow'), // duplicate row, same id
                sharedRes('wf-b', 'Reddit Monitor', 'workflow'),
                sharedRes('fld-x', 'ReadyToPublish', 'workflow_folder'),
                sharedRes('fld-x', 'ReadyToPublish', 'workflow_folder'), // duplicate folder
            ],
        });

        const { result } = renderHook(() => useWorkflowBrowserData('wb/dedup'));
        await waitUntil(result, (s) => s.sharedWorkflows.length > 0);

        // Source lists are deduped.
        expect(result.current.sharedWorkflows.map((w) => w.id).sort()).toEqual(['wf-a', 'wf-b']);
        expect(result.current.sharedFolders.map((f) => f.id)).toEqual(['fld-x']);

        // The rendered root grid data has no duplicate keys.
        const wfIds = result.current.getWorkflows(null).map((w) => w.id);
        expect(wfIds.length).toBe(new Set(wfIds).size);
        const fldIds = result.current.getSubfolders(null).map((f) => f.id);
        expect(fldIds.length).toBe(new Set(fldIds).size);
    });

    it('own workflows win ties over a duplicate shared copy of the same id', async () => {
        socket.replyTo('workflow_folder:get_tree', { folders: [] });
        socket.replyTo('workflow:list', {
            workflows: [{ id: 'wf-a', name: 'My Own', description: '', is_owner: true, user_permission: 'owner', workflow_data: { nodes: [] } }],
        });
        // Same id also shared with the user.
        socket.replyTo('share:list_shared_with_me', { resources: [sharedRes('wf-a', 'Shared Copy', 'workflow')] });

        const { result } = renderHook(() => useWorkflowBrowserData('wb/tie'));
        await waitUntil(result, (s) =>
            (s.workflowsByFolder['']?.some((w: any) => w.id === 'wf-a')) && s.sharedWorkflows.length > 0);

        const wfs = result.current.getWorkflows(null);
        const ids = wfs.map((w) => w.id);
        expect(ids.length).toBe(new Set(ids).size); // no duplicate
        // The owned copy (is_owner true) wins — critical so "Owned by me" keeps it.
        expect(wfs.find((w) => w.id === 'wf-a')?.is_owner).toBe(true);
    });
});
