// @vitest-environment happy-dom
// Following another writer's commits with no host's room (followCommits.ts): a commit heard on the account's change
// stream is read again and folded in, keeping the canvas's own edits; the canvas's own saves are heard and passed by; a
// save on its way lands before the commit is judged; a reset reads again.
import { act, renderHook } from '@testing-library/react';
import { NoClick } from 'noclick';
import { createElement, type ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createWorkLive, WorkLiveContext } from '@/sdk/live';
import { fill } from '@/slots';
import { applyNodeUpdate } from '@/screens/canvas/applyNodeUpdate';
import { GRAPH_SAVES } from '../slots';
import { graphFetch, stored, WORKFLOW } from './fixtures';
import { followCommit, useFollowCommits } from './followCommits';
import { graphRecords, markGraphDirty, reloadFromServer, seedSaveBaseline, setCanvasEditsClient, setCanvasMounted, setGraphLoaded, setGraphVersion } from './liveGraphStore';
import { V1_GRAPH_SAVES } from './saves';

type Json = Record<string, unknown>;

let calls: string[] = [];
let server = stored();
let version = 4;
/** Answers held back until released: each is worked out as the request arrives, then waits. */
let hold = { reads: false, edits: false };
let held: Array<() => void> = [];

beforeEach(() => {
    vi.useFakeTimers();
    for (const id of Object.keys(graphRecords)) delete graphRecords[id];
    fill(GRAPH_SAVES, V1_GRAPH_SAVES);
    calls = [];
    server = stored();
    version = 4;
    hold = { reads: false, edits: false };
    held = [];
    setCanvasEditsClient(
        new NoClick({
            apiKey: 'nk_test',
            baseUrl: 'https://api.test',
            maxRetries: 0,
            fetch: async (input, init) => {
                const request = new Request(input, init);
                calls.push(`${request.method} ${new URL(request.url).pathname}`);
                const answer = await graphFetch({ server: () => server, version: () => version, edit: () => ({ version: ++version }) })(request);
                if (request.method === 'POST' ? hold.edits : hold.reads) await new Promise<void>((done) => held.push(done));
                return answer;
            },
        })
    );
});

afterEach(() => {
    vi.clearAllTimers();
    vi.useRealTimers();
    setCanvasEditsClient(null);
});

async function settle(ms = 0) {
    await vi.advanceTimersByTimeAsync(ms);
    for (let i = 0; i < 30; i++) await Promise.resolve();
}

/** The workflow opened as the canvas opens it: read whole, nothing to save. */
async function open() {
    setCanvasMounted(WORKFLOW, false, true);
    expect(await reloadFromServer(WORKFLOW)).toBe(true);
    setGraphVersion(WORKFLOW, graphRecords[WORKFLOW].graphVersion);
    seedSaveBaseline(WORKFLOW);
    setGraphLoaded(WORKFLOW, true);
    await settle(2500);
    calls = [];
}

/** Another writer adds a step and moves the workflow on a version. */
function theyAdd(id: string) {
    server = { ...server, nodes: [...server.nodes, { id, type: 'log', position: { x: 0, y: 600 }, config: { label: id } }] };
    version += 1;
}

const ids = () => graphRecords[WORKFLOW].nodes.map((n) => n.id);

describe('following other writers’ commits', () => {
    it('reads a newer version again and folds it in, keeping what the canvas changed itself', async () => {
        await open();
        const rec = graphRecords[WORKFLOW];
        rec.nodes = rec.nodes.map((n) => (n.id === 'slack' ? applyNodeUpdate(n, { label: 'Mine' }) : n));
        theyAdd('theirs');
        followCommit(WORKFLOW, version);
        await settle();
        expect(calls).toEqual([`GET /v1/workflows/${WORKFLOW}/graph`]);
        expect(ids()).toEqual(['hook', 'agent', 'slack', 'victim', 'theirs']);
        expect(rec.graphVersion).toBe(5);
        expect((rec.nodes.find((n) => n.id === 'slack')?.data as Json).label).toBe('Mine');
        // The same commit heard again, or an older one, is passed by.
        calls = [];
        followCommit(WORKFLOW, 5);
        followCommit(WORKFLOW, 3);
        await settle();
        expect(calls).toEqual([]);
    });

    it('passes by its own save’s commit, heard while the save is on its way', async () => {
        await open();
        const rec = graphRecords[WORKFLOW];
        rec.nodes = rec.nodes.map((n) => (n.id === 'slack' ? applyNodeUpdate(n, { label: 'Mine' }) : n));
        hold.edits = true;
        markGraphDirty(WORKFLOW);
        await settle(2500);
        expect(calls).toEqual([`POST /v1/workflows/${WORKFLOW}/edits`]);
        expect(rec.saveInFlight).toBe(true);
        // The commit it makes is heard before its answer lands.
        followCommit(WORKFLOW, 5);
        await settle();
        held.shift()?.();
        await settle();
        expect(rec.saveInFlight).toBe(false);
        expect(rec.graphVersion).toBe(5);
        expect(calls).toEqual([`POST /v1/workflows/${WORKFLOW}/edits`]);
    });

    it('reads once for commits heard while a read is on its way, and again for one past it', async () => {
        await open();
        theyAdd('first');
        followCommit(WORKFLOW, version);
        followCommit(WORKFLOW, version);
        await settle();
        expect(calls).toEqual([`GET /v1/workflows/${WORKFLOW}/graph`]);
        calls = [];
        hold.reads = true;
        theyAdd('second');
        followCommit(WORKFLOW, version);
        await settle();
        // Heard while that read is on its way, which reads the workflow as it was before.
        theyAdd('third');
        followCommit(WORKFLOW, version);
        hold.reads = false;
        held.shift()?.();
        await settle();
        expect(calls).toEqual([`GET /v1/workflows/${WORKFLOW}/graph`, `GET /v1/workflows/${WORKFLOW}/graph`]);
        expect(ids().slice(-3)).toEqual(['first', 'second', 'third']);
    });

    it('waits for the load, then follows the stream’s commits to this workflow and its resets', async () => {
        const live = createWorkLive();
        const wrapper = ({ children }: { children: ReactNode }) => createElement(WorkLiveContext.Provider, { value: live }, children);
        renderHook(() => useFollowCommits(WORKFLOW), { wrapper });
        // Not open yet: nothing to fold into.
        act(() => live.deliver('platform:resource', { kind: 'workflow', id: WORKFLOW, status: null, parent_id: null, version: 9 }));
        await settle();
        expect(calls).toEqual([]);

        await open();
        theyAdd('theirs');
        act(() => live.deliver('platform:resource', { kind: 'workflow', id: 'wf_other', status: null, parent_id: null, version: 9 }));
        act(() => live.deliver('platform:resource', { kind: 'deployment', id: WORKFLOW, status: null, parent_id: null, version: 9 }));
        await settle();
        expect(calls).toEqual([]);
        act(() => live.deliver('platform:resource', { kind: 'workflow', id: WORKFLOW, status: null, parent_id: null, version }));
        await settle();
        expect(ids()).toContain('theirs');
        calls = [];
        act(() => live.deliver('reset', { why: 'stream' }));
        await settle();
        expect(calls).toEqual([`GET /v1/workflows/${WORKFLOW}/graph`]);
    });
});
