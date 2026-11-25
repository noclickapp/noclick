// @vitest-environment happy-dom
//
// The Automations page on /v1: its trash read, restored from and emptied through the platform API, and the store's
// writes and reads in the shapes the API answers (a folder tree from the flat folder list, a card's picture from a
// listing's `preview`), each call naming the workspace the page shows.
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { TrashView, daysRemaining } from './TrashView';
import {
    __resetBrowserStoreForTests,
    browserWrites,
    folderTreeOf,
    mapWorkflowApp,
    fetchWorkflows,
    browserStore,
    fetchSharedResources,
} from './workflowBrowserStore';
import { installFakeBrowserClient, listed, listing, settle } from './fakeBrowserClient';

let api: ReturnType<typeof installFakeBrowserClient>;

beforeEach(() => {
    __resetBrowserStoreForTests();
    api = installFakeBrowserClient();
});
afterEach(() => api.teardown());

const DAY = 86_400_000;
const trashed = (id: string, name: string, deletedDaysAgo: number) => {
    const deleted = Date.now() - deletedDaysAgo * DAY - 1000;
    return { object: 'workflow', id, name, description: null, deleted_at: new Date(deleted).toISOString(),
             purge_after: new Date(deleted + 30 * DAY).toISOString() };
};

describe('the trash on /v1', () => {
    it('lists the trash, restores one and deletes one for good', async () => {
        render(<TrashView isMobile={false} />);
        const list = api.last('GET', '/v1/workflows/trash');
        await act(async () => {
            list.answer(listing([trashed('w1', 'Old digest', 2), trashed('w2', 'Morning brief', 29)]));
            await settle();
        });
        expect(screen.getByText('Old digest')).toBeTruthy();
        expect(screen.getByText('Gone in 28 days')).toBeTruthy();
        expect(screen.getByText('Gone in 1 day')).toBeTruthy();

        await act(async () => {
            fireEvent.click(screen.getAllByText('Restore')[0]);
            await settle();
        });
        expect(api.last('POST', '/v1/workflows/w1/restore')).toBeTruthy();
        expect(screen.queryByText('Old digest')).toBeNull();

        await act(async () => {
            fireEvent.click(screen.getByText('Delete forever'));
            await settle();
        });
        await act(async () => {
            fireEvent.click(screen.getByRole('button', { name: /delete/i, hidden: false }));
            await settle();
        });
        expect(api.last('DELETE', '/v1/workflows/w2/trash')).toBeTruthy();
    });

    it('counts days left from when it was deleted', () => {
        expect(daysRemaining(trashed('w', 'x', 0))).toBe(30);
        expect(daysRemaining(trashed('w', 'x', 31))).toBe(0);
    });
});

describe("the store's reads and writes on /v1", () => {
    it('builds the folder tree from the flat list, a teammate\'s folder not the account\'s own', () => {
        const tree = folderTreeOf([
            { id: 'w', name: 'Weekly', parent_id: 'r', depth: 1, workflow_count: 2, access: 'owner' },
            { id: 'r', name: 'Reports', parent_id: null, depth: 0, workflow_count: 0, access: 'owner' },
            { id: 't', name: 'Theirs', parent_id: null, depth: 0, workflow_count: 1, access: 'viewer' },
        ]);
        expect(tree.map((f) => [f.name, f.is_owner, f.path])).toEqual([['Reports', true, '/r/'], ['Theirs', false, '/t/']]);
        expect(tree[0].children!.map((f) => [f.name, f.path, f.workflow_count])).toEqual([['Weekly', '/r/w/', 2]]);
    });

    it("draws a card from a listing's preview and reads a shared one's owner", () => {
        const preview = {
            nodes: [
                { id: 'a', type: 'agent', position: { x: 0, y: 0 }, config: { model: 'claude-code' } },
                { id: 's', type: 'automation-slack', position: { x: 300, y: 0 }, config: { operation: 'send' } },
            ],
            edges: [{ id: 'e', source: 'a', target: 's' }],
        };
        const card = mapWorkflowApp(listed('w1', 'Brief', 'editor', { preview }));
        expect([card.is_owner, card.user_permission, card.owner_name, card.node_count]).toEqual([false, 'edit', 'Ada', 2]);
        expect(card.node_types).toEqual(['agent', 'automation-slack']);
        expect(card.graph_preview?.edges).toHaveLength(1);
    });

    it('lists a team workspace\'s folder with its plan, and what others shared', async () => {
        fetchWorkflows('org_team', 'f1');
        const call = api.last('GET', '/v1/workflows', { folder_id: 'f1' });
        expect(call.query).toEqual({ folder_id: 'f1', organization_id: 'team', include: 'preview' });
        call.answer(listing([listed('w1', 'Brief')]));
        fetchSharedResources();
        api.last('GET', '/v1/workflows', { shared_with_me: 'true' }).answer(listing([
            { object: 'workflow', id: 'w9', name: 'Theirs', access: 'viewer', owner: { name: 'Ada' }, shared_at: '2026-11-22T10:00:00Z' }]));
        api.last('GET', '/v1/workflows/folders', { shared_with_me: 'true' }).answer(listing([]));
        await settle();
        expect(browserStore.scopes['org_team'].workflows['f1'].map((w) => w.name)).toEqual(['Brief']);
        expect(browserStore.shared.workflows.map((w) => [w.name, w.owner_name, w.user_permission])).toEqual([['Theirs', 'Ada', 'view']]);
    });

    it('sends each write to its route, naming the workspace', async () => {
        void browserWrites.createFolder('org_team', { name: 'Reports', description: '', parentId: null });
        await settle();
        expect(api.last('POST', '/v1/workflows/folders').json).toMatchObject({ name: 'Reports', organization_id: 'team' });
        void browserWrites.updateFolder('personal', 'f1', { parentId: null });
        await settle();
        const moved = api.last('PATCH', '/v1/workflows/folders/f1').json!;
        expect(moved.parent_id).toBeNull(); // to the top
        expect('organization_id' in moved && moved.organization_id !== undefined).toBe(false);
        void browserWrites.moveWorkflow('org_team', 'w1', 'f1');
        await settle();
        expect(api.last('POST', '/v1/workflows/w1/move').json).toMatchObject({ folder_id: 'f1', organization_id: 'team' });
        void browserWrites.updateWorkflow('w1', { name: 'Renamed' });
        await settle();
        expect(api.last('POST', '/v1/workflows/w1/edits').json).toMatchObject({ ops: [{ op: 'update_workflow', name: 'Renamed' }] });
        void browserWrites.trashWorkflow('w1');
        await settle();
        expect(api.last('DELETE', '/v1/workflows/w1')).toBeTruthy();
        void browserWrites.deleteFolder('org_team', 'f1');
        await settle();
        expect(api.last('DELETE', '/v1/workflows/folders/f1').query).toEqual({ organization_id: 'team' });
        const fork = browserWrites.forkWorkflow('personal', 'tpl', 'Lead finder');
        await settle();
        const forked = api.last('POST', '/v1/workflows/tpl/fork');
        expect(forked.json).toEqual({ name: 'Lead finder' });
        forked.answer({ id: 'copy', name: 'Lead finder' });
        expect(await fork).toEqual({ id: 'copy', name: 'Lead finder' });
    });

    it('makes a blank workflow in the folder and workspace shown, named by the API', async () => {
        const made = browserWrites.createWorkflow('org_team', 'f1');
        const asked = api.last('POST', '/v1/workflows');
        // No name: the API gives it the next free "Untitled".
        expect(asked.json).toEqual({ folder_id: 'f1', organization_id: 'team' });
        asked.answer({ id: 'w9', name: 'Untitled 2', description: null });
        expect(await made).toEqual({ id: 'w9', name: 'Untitled 2', description: null });
        void browserWrites.createWorkflow('personal', null);
        await settle();
        expect(api.last('POST', '/v1/workflows').json).toEqual({});
    });
});
