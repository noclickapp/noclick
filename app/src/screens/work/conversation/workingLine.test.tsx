// @vitest-environment happy-dom
// The working line under a running turn reads as Claude Code's CLI does: how long, how many tokens, how long it thought.
import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { WorkingLine } from './Activity';

afterEach(() => {
    cleanup();
    vi.useRealTimers();
});

describe('WorkingLine', () => {
    it('shows the clock, the tokens read and written and the thinking', () => {
        vi.useFakeTimers({ now: 100_000 });
        render(<WorkingLine from={86_000} pace={{ tokens: 988, estimated: false, thinkingMs: 10_000, thinkingSince: null, inputTokens: 312_000 }} />);
        expect(screen.getByText('Working').parentElement?.textContent).toBe('✻Working· 14s· ↑ 312k ↓ 988 tokens · thought for 10s');
    });

    it('turns its spinner from the moment the turn is sent, before a word streams', () => {
        vi.useFakeTimers({ now: 100_000 });
        render(<WorkingLine from={100_000} pace={{ tokens: null, estimated: false, thinkingMs: 0, thinkingSince: null }} />);
        const glyph = () => screen.getByTestId('turn-spinner').textContent;
        const first = glyph();
        act(() => vi.advanceTimersByTime(1000));
        expect(screen.getByText('Working').parentElement?.textContent).toContain('· 1s');
        expect(glyph()).not.toBe(first);
    });

    it('shows only the clock before anything streams, and nothing of it while compacting', () => {
        vi.useFakeTimers({ now: 100_000 });
        const { rerender } = render(<WorkingLine from={98_000} pace={{ tokens: null, estimated: false, thinkingMs: 0, thinkingSince: null }} />);
        expect(screen.queryByTestId('turn-pace')).toBeNull();
        rerender(<WorkingLine from={98_000} compacting={99_000} pace={{ tokens: 5, estimated: true, thinkingMs: 0, thinkingSince: null }} />);
        expect(screen.queryByTestId('turn-pace')).toBeNull();
    });
});
