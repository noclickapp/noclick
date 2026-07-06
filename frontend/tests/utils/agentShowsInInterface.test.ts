// Unit tests for agentShowsInInterface — the single rule that decides whether an
// agent renders its chat in the Interface tab. Agents are shown by default and
// only hidden when show_in_interface is explicitly turned off, so this pins the
// "shown unless "false"" semantics that every derivation site relies on.

import { describe, it, expect } from 'vitest';
import { agentShowsInInterface } from '~/utils/interfaceBlocks';

describe('agentShowsInInterface', () => {
    it('shows when unset (default) — absent / null / empty', () => {
        expect(agentShowsInInterface(undefined)).toBe(true);
        expect(agentShowsInInterface(null)).toBe(true);
        expect(agentShowsInInterface('')).toBe(true);
    });

    it('shows when explicitly on ("true" or boolean true)', () => {
        expect(agentShowsInInterface('true')).toBe(true);
        expect(agentShowsInInterface(true)).toBe(true);
    });

    it('hides ONLY when explicitly off ("false" or boolean false)', () => {
        expect(agentShowsInInterface('false')).toBe(false);
        expect(agentShowsInInterface(false)).toBe(false);
    });
});
