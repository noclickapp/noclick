// @vitest-environment jsdom
//
// Tests for the scope-key resync guard in useCachedValtioState. Added when
// fixing the org/workspace/workflow switch staleness: the hook mirrors a
// scoped valtio slice into React state, and before the fix it painted the
// PREVIOUS scope's value for >=1 frame after idbKey (= valtio_path:key) changed
// without a remount, because the post-paint re-sync effect corrected it only
// after commit.
//
// Testing note: these assert COMMITTED FRAMES, not the settled value. A
// useLayoutEffect records the value of every render React actually commits;
// a render discarded by the fix's setState-during-render never commits, so its
// value never appears. A "settled value" assertion (renderHook flushes effects
// in act) would pass with OR without the fix and prove nothing — the whole bug
// is about the frame BEFORE the effect runs.

import { describe, it, expect } from 'vitest';
import { useLayoutEffect } from 'react';
import { renderHook, act } from '@testing-library/react';
import { useCachedValtioState } from '~/hooks/useCachedValtioState';
import { getLocalComponentValtio } from '~/state';

// Seed a scope's in-memory proxy slice directly (what a warm, previously-visited
// scope looks like). The re-seed reads this synchronously in render.
function seed(path: string, key: string, value: unknown) {
    const proxy = getLocalComponentValtio(path);
    if (!proxy.state) proxy.state = {};
    proxy.state[key] = value;
}

describe('useCachedValtioState — scope-key resync', () => {
    it('never commits the previous scope value when valtio_path changes (no stale frame)', () => {
        const key = 'folderTree';
        seed('scope/orgA', key, ['A-folder']);
        seed('scope/orgB', key, ['B-folder']);

        const committed: string[][] = [];
        const { rerender } = renderHook(
            ({ path }) => {
                const [v] = useCachedValtioState<string[]>(path, key, [], true);
                useLayoutEffect(() => { committed.push(v); });
                return v;
            },
            { initialProps: { path: 'scope/orgA' } },
        );

        committed.length = 0; // drop the mount frame(s); we only care about the switch
        rerender({ path: 'scope/orgB' });

        expect(committed).not.toContainEqual(['A-folder']); // the stale frame the bug produced
        expect(committed.at(-1)).toEqual(['B-folder']);      // settles on the new scope
    });

    it('never commits the previous KEY value when only the key changes (workspace-scoped key)', () => {
        const path = 'noclick-usage';
        seed(path, 'last7days-org-x', { total: 111 });
        seed(path, 'last7days-personal', { total: 222 });

        const committed: Array<{ total: number }> = [];
        const { rerender } = renderHook(
            ({ key }) => {
                const [v] = useCachedValtioState<{ total: number }>(path, key, { total: 0 }, true);
                useLayoutEffect(() => { committed.push(v); });
                return v;
            },
            { initialProps: { key: 'last7days-org-x' } },
        );

        committed.length = 0;
        rerender({ key: 'last7days-personal' });

        expect(committed).not.toContainEqual({ total: 111 });
        expect(committed.at(-1)).toEqual({ total: 222 });
    });

    it('commits initialValue (never the previous scope) for a cold scope', async () => {
        const key = 'ownershipFilter';
        seed('scope/warm', key, 'not_owned');

        const committed: string[] = [];
        const { rerender } = renderHook(
            ({ path }) => {
                const [v] = useCachedValtioState<string>(path, key, 'all', true);
                useLayoutEffect(() => { committed.push(v); });
                return v;
            },
            { initialProps: { path: 'scope/warm' } },
        );

        committed.length = 0;
        await act(async () => {
            rerender({ path: 'scope/cold-ownership' });
            await Promise.resolve(); // let the cold IndexedDB/session read settle
        });

        expect(committed).not.toContain('not_owned'); // no leak of the previous scope
        expect(committed.at(-1)).toBe('all');
    });

    it('does NOT re-seed on unrelated re-renders (stable idbKey keeps its value)', () => {
        const { result, rerender } = renderHook(
            ({ path }) => useCachedValtioState<number>(path, 'counter', 0, true),
            { initialProps: { path: 'scope/static' } },
        );
        act(() => {
            result.current[1](5);
        });
        expect(result.current[0]).toBe(5);

        // Same path+key: a re-render must not clobber the set value back to initial.
        rerender({ path: 'scope/static' });
        expect(result.current[0]).toBe(5);
    });

    it('functional updates chain synchronously within a slot', () => {
        const { result } = renderHook(() =>
            useCachedValtioState<number>('scope/burst', 'counter', 0, true),
        );

        // Burst of functional updates between renders — each must see the
        // previous one's value (the usage dashboard's real-time usage:event
        // cache path applies events this way).
        act(() => {
            result.current[1]((prev) => prev + 1);
            result.current[1]((prev) => prev + 1);
            result.current[1]((prev) => prev + 1);
        });
        expect(result.current[0]).toBe(3);
    });
});
