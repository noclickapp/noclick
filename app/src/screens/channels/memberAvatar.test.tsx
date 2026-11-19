// @vitest-environment happy-dom
// A channel member's avatar: an agent is its face (AGENT_FACE: its initials on its own colour's disc unless whoever
// runs the app fills it), given its job and its live state; a person is their initial; NoClick is its mark.
import { cleanup, render } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { fill } from '@/slots';
import { AgentRolesContext, MemberAvatar, presenceFace } from './avatars';
import { AVATAR_HUE } from './model';
import { AGENT_FACE, type AgentFaceProps } from './slots';
import { InitialsFace } from './slotStandards';
import type { ChannelMember } from './types';

afterEach(() => {
    cleanup();
    fill(AGENT_FACE, InitialsFace);
});

const SCOUT: ChannelMember = { id: 'mem_scout', kind: 'agent', name: 'Scout', agentId: 'agt_scout', hue: 'teal' };
const PRIYA: ChannelMember = { id: 'mem_priya', kind: 'human', name: 'Priya Shah' };

const initials = (el: HTMLElement) => el.querySelector<HTMLElement>('[data-agent-initials]');

describe('an agent’s avatar', () => {
    it('is its letters on its own colour’s disc, white on it, at its size', () => {
        const { container } = render(<MemberAvatar member={{ ...SCOUT, initials: 'SC' }} size={32} />);
        const face = initials(container)!;
        expect(face.textContent).toBe('SC');
        expect(face.style.backgroundColor).toBe(AVATAR_HUE.teal);
        expect(face.className).toContain('h-8');
        expect(face.className).toContain('text-white');
        expect(face.getAttribute('aria-hidden')).toBe('true');
    });

    it('reads its letters off its name where the room gave it none', () => {
        expect(initials(render(<MemberAvatar member={{ ...SCOUT, name: 'Launch Writer' }} size={24} />).container)!.textContent).toBe('LW');
    });

    it('is whatever face fills AGENT_FACE, handed its job (as the account keeps it, else its own), state, marks and size', () => {
        const seen: Omit<AgentFaceProps, 'member'>[] = [];
        fill(AGENT_FACE, ({ member, ...rest }: AgentFaceProps) => {
            seen.push(rest);
            return <span data-face={member.agentId} className={rest.className} />;
        });
        const { container } = render(
            <AgentRolesContext.Provider value={new Map([['agt_scout', 'Plans the kitchen’s recipes']])}>
                <MemberAvatar member={SCOUT} size={20} state="needs" marks={false} className="ring-2" />
            </AgentRolesContext.Provider>
        );
        expect(container.querySelector('[data-face="agt_scout"]')).toBeTruthy();
        expect(initials(container)).toBeNull();
        expect(seen).toEqual([{ role: 'Plans the kitchen’s recipes', size: 20, state: 'needs', marks: false, className: 'h-5 w-5 text-[10px] ring-2' }]);
        cleanup();
        render(<MemberAvatar member={{ ...SCOUT, role: 'Finds events' }} size={32} />);
        expect(seen.at(-1)).toMatchObject({ role: 'Finds events', size: 32, state: undefined });
    });

    it('is at work in a channel while it takes a turn, and rests still otherwise', () => {
        expect(presenceFace({ ...SCOUT, busy: true })).toBe('working');
        expect(presenceFace(SCOUT)).toBeUndefined();
    });
});

describe('everyone else', () => {
    it('is a person’s initial on a quiet disc', () => {
        const { container } = render(<MemberAvatar member={PRIYA} size={32} />);
        expect(initials(container)).toBeNull();
        expect(container.textContent).toBe('P');
    });

    it('is NoClick’s mark for NoClick', () => {
        const { container } = render(<MemberAvatar member={{ ...SCOUT, noclick: true }} size={32} />);
        expect(initials(container)).toBeNull();
        expect(container.querySelector('[data-noclick-mark]')).toBeTruthy();
    });
});
