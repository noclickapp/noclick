// Unit tests for agentShowsInInterface — the single rule that decides whether an
// agent renders its chat in the Interface tab. Agents are shown by default and
// only hidden when show_in_interface is explicitly turned off, so this pins the
// "shown unless "false"" semantics that every derivation site relies on.

import { describe, it, expect } from 'vitest';
import {
    agentShowsInInterface,
    hiddenAgentToRevealForTestRun,
} from '~/utils/interfaceBlocks';

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

// The run_test hand-off's un-hide rule: the Test Run screen renders inside an
// agent's interface chat block, so when every agent is hidden the hand-off
// must flip one back on — otherwise the sticky open-test/autorun flags arm
// with no consumer (the AI builder used to hide "background" agents and then
// fire <run_test/> into the hidden block).
describe('hiddenAgentToRevealForTestRun', () => {
    const agent = (id: string, show?: unknown) => ({
        id,
        type: 'agent',
        data: show === undefined ? {} : { config: { show_in_interface: show } },
    });

    it('returns the first agent when all agents are hidden', () => {
        const nodes = [
            { id: 'trigger', type: 'automation-gmail' },
            agent('a1', 'false'),
            agent('a2', 'false'),
        ];
        expect(hiddenAgentToRevealForTestRun(nodes)).toBe('a1');
    });

    it('returns null when any agent already shows (default or explicit)', () => {
        expect(
            hiddenAgentToRevealForTestRun([agent('a1', 'false'), agent('a2')])
        ).toBeNull();
        expect(
            hiddenAgentToRevealForTestRun([agent('a1', 'true')])
        ).toBeNull();
    });

    it('returns null when the workflow has no agent', () => {
        expect(
            hiddenAgentToRevealForTestRun([
                { id: 'trigger', type: 'automation-gmail' },
                { id: 'form', type: 'interface-form' },
            ])
        ).toBeNull();
    });

    it('reads the backend flat-config shape too', () => {
        expect(
            hiddenAgentToRevealForTestRun([
                { id: 'a1', type: 'agent', config: { show_in_interface: 'false' } },
            ])
        ).toBe('a1');
    });
});
