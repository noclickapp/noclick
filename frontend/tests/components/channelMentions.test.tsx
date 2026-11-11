// @vitest-environment jsdom
// A message's @mentions: each that names one member of the channel is drawn as one, resolved as the platform resolves
// them (by name, ignoring case); anything else stays plain.
import { cleanup, render } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { MessageBody } from '~/components/shell/channels/MessageBody';
import { YOU } from '~/components/shell/channels/model';
import type { ChannelMember } from '~/components/shell/channels/types';

afterEach(cleanup);

const GROWTH: ChannelMember = { id: 'm_growth', kind: 'agent', name: 'Growth', hue: 'emerald' };
const PRIYA: ChannelMember = { id: 'm_priya', kind: 'human', name: 'Priya Shah' };
const NO_CHANNELS = new Map<string, string>();

function mentionsOf(text: string, members: ChannelMember[] = [YOU, GROWTH, PRIYA]) {
    const { container } = render(<MessageBody text={text} members={members} channels={NO_CHANNELS} onChannel={() => undefined} />);
    return [...container.querySelectorAll<HTMLElement>('[data-mention]')].map((el) => ({ text: el.textContent, kind: el.dataset.mention, className: el.className }));
}

describe('a message’s mentions', () => {
    it('draws an agent’s in its colour on its tint, a person’s in the accent, and yours', () => {
        const found = mentionsOf('@Growth, can you and @Priya Shah check it? cc @You');
        expect(found.map(({ text, kind }) => [text, kind])).toEqual([
            ['@Growth', 'agent'],
            ['@Priya Shah', 'human'],
            ['@You', 'you'],
        ]);
        expect(found[0].className).toContain('text-emerald-700');
        expect(found[0].className).toContain('bg-emerald-500/[0.14]');
        expect(found[1].className).toContain('bg-accent');
    });

    it('resolves a name in any case, as the platform does', () => {
        expect(mentionsOf('thanks @growth').map((m) => m.text)).toEqual(['@growth']);
    });

    it('leaves plain what names no one, or several', () => {
        expect(mentionsOf('@Growthy and mail@Growth and @Nobody')).toEqual([]);
        // Two members by one name: a mention names neither.
        const twins: ChannelMember[] = [YOU, { id: 'a1', kind: 'agent', name: 'Agent', hue: 'sky' }, { id: 'a2', kind: 'agent', name: 'agent', hue: 'violet' }];
        expect(mentionsOf('@Agent, look at this', twins)).toEqual([]);
        // One of them alone is named, whichever case it's written in.
        expect(mentionsOf('@AGENT, look', twins.slice(0, 2)).map((m) => m.text)).toEqual(['@AGENT']);
    });

    it('keeps a mention inside code as code', () => {
        expect(mentionsOf('run `@Growth deploy` later')).toEqual([]);
    });
});
