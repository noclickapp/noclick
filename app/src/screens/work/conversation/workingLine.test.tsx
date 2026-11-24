// @vitest-environment happy-dom
// The working line under a running turn reads as Claude Code's CLI does: how long, how many tokens, how long it thought.
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { WorkingLine } from './Activity';

afterEach(() => {
    cleanup();
    vi.useRealTimers();
});

describe('WorkingLine', () => {
    it('shows the clock, the tokens written and the thinking', () => {
        vi.useFakeTimers({ now: 100_000 });
        render(<WorkingLine from={86_000} pace={{ tokens: 988, estimated: false, thinkingMs: 10_000, thinkingSince: null }} />);
        expect(screen.getByText('Working for').parentElement?.textContent).toBe('Working for14s· ↓ 988 tokens · thought for 10s');
    });

    it('shows only the clock before anything streams, and nothing of it while compacting', () => {
        vi.useFakeTimers({ now: 100_000 });
        const { rerender } = render(<WorkingLine from={98_000} pace={{ tokens: null, estimated: false, thinkingMs: 0, thinkingSince: null }} />);
        expect(screen.queryByTestId('turn-pace')).toBeNull();
        rerender(<WorkingLine from={98_000} compacting={99_000} pace={{ tokens: 5, estimated: true, thinkingMs: 0, thinkingSince: null }} />);
        expect(screen.queryByTestId('turn-pace')).toBeNull();
    });
});
