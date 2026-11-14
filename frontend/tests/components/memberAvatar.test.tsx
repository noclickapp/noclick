// @vitest-environment happy-dom
// A channel member's avatar: an agent is its mascot on its own colour's disc, dressed by its role and wearing its live
// state; a person is their initial; NoClick is its mark. A mascot with no state rests, still, and reduced motion
// stills every one.
import { cleanup, render } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { AgentRolesContext, MemberAvatar, presenceFace } from '~/components/shell/channels/avatars';
import { AVATAR_HUE, MASCOT_MOTION_CSS } from '~/components/shell/channels/mascot/AgentMascot';
import { STATES, type MascotState } from '~/components/shell/channels/mascot/kit';
import type { ChannelMember } from '~/components/shell/channels/types';

afterEach(cleanup);

const SCOUT: ChannelMember = { id: 'mem_scout', kind: 'agent', name: 'Scout', agentId: 'agt_scout', hue: 'teal' };
const PRIYA: ChannelMember = { id: 'mem_priya', kind: 'human', name: 'Priya Shah' };

const face = (el: HTMLElement) => el.querySelector<HTMLElement>('[data-mascot]');

describe('an agent’s avatar', () => {
    it('is its mascot on its own colour’s disc, never its letters', () => {
        const { container } = render(<MemberAvatar member={{ ...SCOUT, initials: 'S' }} size={32} />);
        const mascot = face(container)!;
        expect(mascot.querySelector('svg')).toBeTruthy();
        expect(mascot.textContent).toBe('');
        expect(mascot.style.getPropertyValue('--d')).toBe(AVATAR_HUE.teal);
        expect(mascot.className).toContain('h-8');
    });

    it('is the same agent wherever it’s drawn, seeded by which agent it is rather than its seat in a channel', () => {
        const a = render(<MemberAvatar member={SCOUT} size={48} />).container.innerHTML;
        cleanup();
        const b = render(<MemberAvatar member={{ ...SCOUT, id: 'mem_elsewhere' }} size={48} />).container.innerHTML;
        cleanup();
        const other = render(<MemberAvatar member={{ ...SCOUT, agentId: 'agt_other' }} size={48} />).container.innerHTML;
        expect(b).toBe(a);
        expect(other).not.toBe(a);
    });

    it('is dressed by its job, as the account keeps it, where the surface knows only its name', () => {
        const bare = render(<MemberAvatar member={SCOUT} size={48} />).container.innerHTML;
        cleanup();
        const roles = new Map([['agt_scout', 'Plans the kitchen’s recipes']]);
        const dressed = render(
            <AgentRolesContext.Provider value={roles}>
                <MemberAvatar member={SCOUT} size={48} />
            </AgentRolesContext.Provider>
        ).container.innerHTML;
        cleanup();
        // Its own role on the member dresses it the same way.
        const own = render(<MemberAvatar member={{ ...SCOUT, role: 'Plans the kitchen’s recipes' }} size={48} />).container.innerHTML;
        expect(dressed).not.toBe(bare);
        expect(own).toBe(dressed);
    });

    it('wears its live state as a face and a loop, and rests still without one', () => {
        const still = face(render(<MemberAvatar member={SCOUT} size={32} />).container)!;
        expect(still.dataset.mascot).toBe('waiting');
        expect(still.hasAttribute('data-still')).toBe(true);
        expect(still.className).not.toMatch(/\bncm-(working|waiting|needs|asleep|done|failed)\b/);
        cleanup();
        for (const state of Object.keys(STATES) as MascotState[]) {
            const live = face(render(<MemberAvatar member={SCOUT} size={32} state={state} />).container)!;
            expect(live.dataset.mascot).toBe(state);
            expect(live.className).toContain(`ncm-${state}`);
            expect(live.style.getPropertyValue('--ph')).toMatch(/^-\d+\.\d\ds$/);
            cleanup();
        }
    });

    it('at 20px and under takes the ring when it needs you, a red dot when it failed, and fades asleep', () => {
        const at = (size: 20 | 24, state: MascotState) => face(render(<MemberAvatar member={SCOUT} size={size} state={state} />).container)!;
        expect(at(20, 'needs').querySelector('.ncm-ring')).toBeTruthy();
        expect(at(20, 'failed').querySelector('.ncm-dot')).toBeTruthy();
        expect(at(20, 'asleep').className).toContain('ncm-faded');
        expect(at(20, 'working').querySelector('.ncm-ring, .ncm-dot')).toBeNull();
        // From 24px its face and marks say it.
        expect(at(24, 'needs').querySelector('.ncm-ring')).toBeNull();
        expect(at(24, 'failed').querySelector('.ncm-dot')).toBeNull();
        expect(at(24, 'failed').querySelector('.m-rd')).toBeTruthy();
    });

    it('is at work in a channel while it takes a turn, and rests still otherwise', () => {
        expect(presenceFace({ ...SCOUT, busy: true })).toBe('working');
        expect(presenceFace(SCOUT)).toBeUndefined();
    });
});

describe('the mascots’ motion', () => {
    const rules = MASCOT_MOTION_CSS.replace(/@media[^{]*\{[^]*$/, '')
        .split('\n')
        .filter((line) => /animation(-name)?\s*:/.test(line));

    it('moves only a mascot showing a state, and only in that state’s loop', () => {
        expect(rules.length).toBeGreaterThan(10);
        for (const rule of rules) expect(rule).toMatch(/^\.ncm-(working|waiting|needs|asleep|done|failed) /);
    });

    it('stills every mascot under reduced motion', () => {
        expect(MASCOT_MOTION_CSS).toMatch(/@media \(prefers-reduced-motion: reduce\) \{ \.nc-mascot \* \{ animation: none !important \} \}$/);
    });
});

describe('everyone else', () => {
    it('is a person’s initial on a quiet disc', () => {
        const { container } = render(<MemberAvatar member={PRIYA} size={32} />);
        expect(face(container)).toBeNull();
        expect(container.textContent).toBe('P');
    });

    it('is NoClick’s mark for NoClick', () => {
        const { container } = render(<MemberAvatar member={{ ...SCOUT, noclick: true }} size={32} />);
        expect(face(container)).toBeNull();
        expect(container.querySelector('[data-noclick-mark]')).toBeTruthy();
    });
});
