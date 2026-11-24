// @vitest-environment happy-dom
//
// Regression test for the duplicate-key bug: the shared-with-me list could return
// the same resource under multiple share rows (direct share + shared-folder
// descendant), so sharedWorkflows/sharedFolders arrived with duplicate ids. Those
// flow into the root grid as React keys; duplicate keys corrupt reconciliation,
// which rendered visible duplicate cards AND left stale cards in the DOM across
// org switches (store correct, DOM stale). getWorkflows/getSubfolders (and the
// shared-list setters) now dedup by id so the rendered lists never carry dup keys.

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useWorkflowBrowserData } from './useWorkflowBrowserData';
import { __resetBrowserStoreForTests } from './workflowBrowserStore';
import { installFakeBrowserClient, listed, listing, settle } from './fakeBrowserClient';

let api: ReturnType<typeof installFakeBrowserClient>;

beforeEach(() => { __resetBrowserStoreForTests(); api = installFakeBrowserClient(); });
afterEach(() => api.teardown());

/** Answers every call as it's made: `shared` for the shared-with-me lists, `root` for the root listing. */
type Data = ReturnType<typeof useWorkflowBrowserData>;

async function answering(result: { current: Data }, answers: { shared: unknown[]; sharedFolders: unknown[]; root: unknown[] },
                         cond: (s: Data) => boolean) {
    for (let i = 0; i < 20 && !cond(result.current); i++) {
        await act(async () => {
            for (const call of api.calls.splice(0)) {
                if (call.query.shared_with_me) call.answer(listing(call.path.endsWith('folders') ? answers.sharedFolders : answers.shared));
                else if (call.path.endsWith('folders')) call.answer(listing([]));
                else call.answer(listing(answers.root));
            }
            await settle();
        });
    }
}

function sharedRes(id: string, name: string, type: 'workflow' | 'workflow_folder') {
    return {
        object: type, id, name, description: null, access: 'editor', owner: { name: 'Owner' },
        shared_at: '2026-01-01T00:00:00Z',
    };
}

describe('useWorkflowBrowserData — dedup shared resources by id', () => {
    it('drops duplicate ids from the shared lists so the grid has no duplicate React keys', async () => {
        const { result } = renderHook(() => useWorkflowBrowserData('wb/dedup'));
        await answering(result, {
            root: [],
            shared: [
                sharedRes('wf-a', 'Twitter Monitor', 'workflow'),
                sharedRes('wf-a', 'Twitter Monitor', 'workflow'), // duplicate row, same id
                sharedRes('wf-b', 'Reddit Monitor', 'workflow'),
            ],
            sharedFolders: [
                sharedRes('fld-x', 'ReadyToPublish', 'workflow_folder'),
                sharedRes('fld-x', 'ReadyToPublish', 'workflow_folder'), // duplicate folder
            ],
        }, (s) => s.sharedWorkflows.length > 0);

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
        const { result } = renderHook(() => useWorkflowBrowserData('wb/tie'));
        // Same id also shared with the user.
        await answering(result, {
            root: [listed('wf-a', 'My Own', 'owner', { preview: { nodes: [], edges: [] } })],
            shared: [sharedRes('wf-a', 'Shared Copy', 'workflow')],
            sharedFolders: [],
        }, (s) => (s.workflowsByFolder['']?.some((w: any) => w.id === 'wf-a')) && s.sharedWorkflows.length > 0);

        const wfs = result.current.getWorkflows(null);
        const ids = wfs.map((w) => w.id);
        expect(ids.length).toBe(new Set(ids).size); // no duplicate
        // The owned copy (is_owner true) wins — critical so "Owned by me" keeps it.
        expect(wfs.find((w) => w.id === 'wf-a')?.is_owner).toBe(true);
    });
});
