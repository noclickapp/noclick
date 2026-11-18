// @vitest-environment happy-dom
// The console reads again what a platform:resource frame says moved, from the live source its host hands it (the
// frames a host's own connection brings), and nothing else; a host with no live source leaves reads to their own re-reads.
import { act, cleanup, render, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { createWorkLive, type WorkLive } from '@/sdk/live';
import { useV1 } from '@/sdk/useV1';
import { ConsoleProviders } from './ConsoleProviders';
import { fixtureConsole } from './fixtures/context';

afterEach(cleanup);

function Reader({ path, reads }: { path: string; reads: string[] }) {
    useV1(path, async () => {
        reads.push(path);
        return path;
    });
    return null;
}

function mount(live: WorkLive | null) {
    const reads: string[] = [];
    const view = render(
        <ConsoleProviders value={fixtureConsole({ live })}>
            <Reader path="domains/dom_1" reads={reads} />
            <Reader path="repos/repo_1" reads={reads} />
        </ConsoleProviders>
    );
    const count = (path: string) => reads.filter((read) => read === path).length;
    return { view, count };
}

describe('the console’s live frames', () => {
    it('read again what a frame says moved, and only that', async () => {
        const live = createWorkLive();
        const { count } = mount(live);
        await waitFor(() => expect([count('domains/dom_1'), count('repos/repo_1')]).toEqual([1, 1]));
        act(() => live.deliver('platform:resource', { kind: 'domain', id: 'dom_1', status: 'active' }));
        await waitFor(() => expect(count('domains/dom_1')).toBe(2));
        expect(count('repos/repo_1')).toBe(1);
    });

    it('stop once the console is gone', async () => {
        const live = createWorkLive();
        const { view, count } = mount(live);
        await waitFor(() => expect(count('repos/repo_1')).toBe(1));
        view.unmount();
        act(() => live.deliver('platform:resource', { kind: 'repo', id: 'repo_1', status: 'active' }));
        await new Promise((done) => setTimeout(done, 20));
        expect(count('repos/repo_1')).toBe(1);
    });

    it('are optional: a host with none still reads', async () => {
        const { count } = mount(null);
        await waitFor(() => expect([count('domains/dom_1'), count('repos/repo_1')]).toEqual([1, 1]));
    });
});
