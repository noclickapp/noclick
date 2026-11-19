// The account's change stream says who is typing by id alone: the line names them as the channel's members do, and
// someone not among them yet as "Someone". A name the change carries still wins.
import { describe, expect, it } from 'vitest';
import type { ChannelMember } from '@/screens/channels/types';
import type { Typist } from '@/screens/channels/typing';
import { workingLineOf } from './WorkingLine';

const ASHA: ChannelMember = { id: 'm_asha', kind: 'human', name: 'Asha Rao', userId: 'usr_asha' };
const typist = (id: string, name = ''): Typist => ({ id, name, until: Date.now() + 5_000 });
const line = (typists: Typist[]) => workingLineOf({ channelId: 'ch_1', members: [ASHA], busy: [], states: [], messages: [], typists });

describe('a typist the change didn’t name', () => {
    it('is named as the channel’s members name them', () => {
        expect(line([typist('usr_asha')]).typing?.names).toBe('Asha Rao');
    });

    it('is someone when they aren’t among its members yet', () => {
        const drawn = line([typist('usr_new')]).typing;
        expect(drawn?.names).toBe('Someone');
        expect(drawn?.faces.map((f) => f.name)).toEqual(['Someone']);
    });

    it('keeps the name a change gave', () => {
        expect(line([typist('usr_asha', 'Asha')]).typing?.names).toBe('Asha');
    });
});
