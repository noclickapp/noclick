// How a channel's agents are told apart: the letters on their avatars come from what sets their names apart (two
// agents named "Paws & Pace …" both drew "P"), and each wears a colour no other agent in the room does, from a
// palette whose every pair stays apart in both themes and for colour-blind readers.
import { describe, expect, it } from 'vitest';
import { AGENT_HUES, hueFor, initialsAmong, seatMembers } from '~/components/shell/channels/model';
import type { ChannelMember } from '~/components/shell/channels/types';

const agent = (id: string, name: string): ChannelMember => ({ id: `mem_${id}`, kind: 'agent', name, agentId: id });

describe('an agent’s letters', () => {
    it('come from the part of its name that sets it apart, else its first letter', () => {
        // The 10-27 film run's pair.
        expect(initialsAmong(['Paws & Pace Austin Events Researcher', 'Paws & Pace Newsletter Writer'])).toEqual(['R', 'W']);
        expect(initialsAmong(['Scout', 'Quill'])).toEqual(['S', 'Q']);
        // Only names that share words look past them, at both ends; a third with words of its own keeps its first letter.
        expect(initialsAmong(['Acme Sales Agent', 'Acme Support Agent', 'Ledger'])).toEqual(['Sa', 'Su', 'L']);
        expect(initialsAmong(['Inbox Triage Agent', 'Billing Agent'])).toEqual(['T', 'B']);
        // Still alike after that: the last two words' initials, or one word's first two letters.
        expect(initialsAmong(['Team Events Researcher', 'Team Copy Reviewer'])).toEqual(['ER', 'CR']);
        expect(initialsAmong(['Sage', 'Scout'])).toEqual(['Sa', 'Sc']);
        // A name inside another keeps its own word.
        expect(initialsAmong(['Writer', 'Writer Bot'])).toEqual(['W', 'B']);
        expect(initialsAmong(['lower case'])).toEqual(['L']);
    });
});

describe('a room’s colours', () => {
    it('give every agent in a room a colour of its own, its own one while it’s free', () => {
        const ids = ['a1', 'a2', 'a3', 'a4', 'a5'];
        const seated = seatMembers([{ id: 'you', kind: 'you', name: 'You' }, ...ids.map((id) => agent(id, `Agent ${id}`))]);
        const hues = seated.filter((m) => m.kind === 'agent').map((m) => m.hue);
        expect(new Set(hues).size).toBe(AGENT_HUES.length);
        // The first agent always wears its own; a person is left as they are.
        expect(seated[1].hue).toBe(hueFor('a1'));
        expect(seated[0]).toEqual({ id: 'you', kind: 'you', name: 'You' });
    });

    it('moves the later of two agents whose own colours match to the next free one', () => {
        // Two ids whose own colour is the same.
        const first = 'agent-0';
        const twin = Array.from({ length: 200 }, (_, i) => `agent-${i + 1}`).find((id) => hueFor(id) === hueFor(first))!;
        const [a, b] = seatMembers([agent(first, 'Paws & Pace Austin Events Researcher'), agent(twin, 'Paws & Pace Newsletter Writer')]);
        expect(a.hue).toBe(hueFor(first));
        expect(b.hue).not.toBe(a.hue);
        expect([a.initials, b.initials]).toEqual(['R', 'W']);
    });
});
