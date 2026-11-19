import { describe, expect, it } from 'vitest';
import { moveHeading, moveState } from './move';

const NOW = Date.UTC(2026, 10, 13, 5, 0);
const later = new Date(NOW + 20 * 60_000);
const earlier = new Date(NOW - 60_000);

describe('a move as the person reads it', () => {
    it('reads a refusal the agent can still fix as waiting on it, not as stopped', () => {
        const move = { status: 'failed' as const, expiresAt: later };
        expect(moveState(move, NOW)).toBe('open');
        expect(moveHeading(move, NOW).title).toBe('Waiting on your agent');
    });

    it('stops only once the move is over', () => {
        expect(moveHeading({ status: 'failed', expiresAt: earlier }, NOW).title).toBe('The move stopped');
        expect(moveHeading({ status: 'expired', expiresAt: earlier }, NOW)).toEqual({
            title: 'The move stopped',
            line: 'Its time ran out before it finished. Get a new code to move it again.',
        });
        expect(moveHeading({ status: 'canceled', expiresAt: later }, NOW).line).toBe('It was called off.');
    });

    it('is moving while it carries and finishes, and moved once done', () => {
        expect(moveHeading({ status: 'moving', expiresAt: later }, NOW).title).toBe('Moving it in');
        expect(moveHeading({ status: 'finishing', expiresAt: later }, NOW).title).toBe('Moving it in');
        expect(moveState({ status: 'done', expiresAt: earlier }, NOW)).toBe('done');
    });
});
