// @vitest-environment happy-dom
// A reference scrolled to is let go of after a moment, while the provider is mounted; once it has gone, nothing is left
// pending.
import { act, renderHook } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ReferenceHoverProvider, useReferenceHover } from './ReferenceHoverContext';

beforeEach(() => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
});

afterEach(() => {
    vi.useRealTimers();
});

const wrapper = ({ children }: { children: ReactNode }) => <ReferenceHoverProvider>{children}</ReferenceHoverProvider>;

describe('scrolling to a reference', () => {
    it('lets it go after a moment', () => {
        const { result, unmount } = renderHook(() => useReferenceHover(), { wrapper });
        act(() => result.current!.setScrollToReference({ nodeId: 'fetch', path: 'data.items[0]' }));
        expect(result.current!.scrollToReference).not.toBeNull();
        act(() => vi.advanceTimersByTime(800));
        expect(result.current!.scrollToReference).toBeNull();
        expect(result.current!.pathsToExpand.size).toBe(0);
        unmount();
    });

    it('leaves nothing pending once the provider has gone', () => {
        const { result, unmount } = renderHook(() => useReferenceHover(), { wrapper });
        act(() => result.current!.setScrollToReference({ nodeId: 'fetch', path: 'data.items[0]' }));
        expect(vi.getTimerCount()).toBe(1);
        unmount();
        expect(vi.getTimerCount()).toBe(0);
    });
});
