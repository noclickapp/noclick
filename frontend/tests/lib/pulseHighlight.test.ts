// @vitest-environment jsdom
//
// Tests for the shared "look here" pulse ring.
//
// The behavior that carries real risk is re-pulsing an element that's already
// mid-animation: the missing-fields banner is one DOM element reused across
// node selections, so stepping through incomplete nodes pulses the same element
// twice in a row. Without the restart it looks like a dead click, and without
// clearing the previous removal timer the second pulse gets cut short.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
    BANNER_PULSE_CYCLES,
    claimPulse,
    credentialsPulseKey,
    onPulseRequested,
    pulseElement,
    requestPulse,
} from '~/lib/pulseHighlight';

const PULSE_CLASS = 'deep-link-highlight';
const CYCLE_MS = 600;
const SLACK_MS = 800;

let el: HTMLElement;

beforeEach(() => {
    vi.useFakeTimers();
    document.body.innerHTML = '';
    el = document.createElement('div');
    document.body.append(el);
});

afterEach(() => {
    vi.useRealTimers();
});

describe('pulseElement', () => {
    it('applies the pulse class and clears it after the animation', () => {
        pulseElement(el);
        expect(el.classList.contains(PULSE_CLASS)).toBe(true);

        vi.advanceTimersByTime(2 * CYCLE_MS + SLACK_MS - 1);
        expect(el.classList.contains(PULSE_CLASS)).toBe(true);
        vi.advanceTimersByTime(1);
        expect(el.classList.contains(PULSE_CLASS)).toBe(false);
    });

    it('defaults to two cycles, the long-standing field-control behavior', () => {
        pulseElement(el);
        expect(el.style.getPropertyValue('--pulse-cycles')).toBe('2');
    });

    it('holds longer for more cycles so the ring is never cut off mid-flash', () => {
        // The count drives the CSS iteration count AND the hold time from one
        // number; if those drifted, a 3-cycle pulse would be stripped during
        // its third flash.
        pulseElement(el, { cycles: BANNER_PULSE_CYCLES });
        expect(el.style.getPropertyValue('--pulse-cycles')).toBe('3');

        vi.advanceTimersByTime(2 * CYCLE_MS + SLACK_MS);
        expect(el.classList.contains(PULSE_CLASS)).toBe(true);

        vi.advanceTimersByTime(CYCLE_MS);
        expect(el.classList.contains(PULSE_CLASS)).toBe(false);
    });

    it('cleans up the cycles variable when the pulse ends', () => {
        pulseElement(el, { cycles: 3 });
        vi.advanceTimersByTime(3 * CYCLE_MS + SLACK_MS);
        expect(el.style.getPropertyValue('--pulse-cycles')).toBe('');
    });

    it('leaves the corner radius to CSS unless asked', () => {
        // A field control wants the stylesheet default; only a padded region
        // wrapping several controls overrides it, and an always-set variable
        // would make that the caller's problem everywhere.
        pulseElement(el);
        expect(el.style.getPropertyValue('--pulse-radius')).toBe('');
    });

    it('rounds the ring to match a padded region, and cleans that up too', () => {
        pulseElement(el, { radius: 14 });
        expect(el.style.getPropertyValue('--pulse-radius')).toBe('14px');

        vi.advanceTimersByTime(2 * CYCLE_MS + SLACK_MS);
        expect(el.style.getPropertyValue('--pulse-radius')).toBe('');
    });

    it('restarts rather than no-ops when re-pulsed mid-animation', () => {
        // React reuses the banner element across node selections, so a second
        // arrow click finds the class already applied. Re-adding it does
        // nothing; the class has to come off and go back on around a reflow.
        const removals: boolean[] = [];
        const realRemove = el.classList.remove.bind(el.classList);
        el.classList.remove = (...args: string[]) => {
            removals.push(args.includes(PULSE_CLASS));
            realRemove(...args);
        };

        pulseElement(el);
        vi.advanceTimersByTime(500);
        pulseElement(el);

        expect(removals[removals.length - 1]).toBe(true);
        expect(el.classList.contains(PULSE_CLASS)).toBe(true);
    });

    it('gives a re-pulse its own full duration', () => {
        // The first pulse's removal timer must be cancelled — otherwise it
        // fires partway through the second and strips the ring early.
        pulseElement(el);
        vi.advanceTimersByTime(1500);
        pulseElement(el);

        vi.advanceTimersByTime(600);
        expect(el.classList.contains(PULSE_CLASS)).toBe(true);
    });

    it('tracks pulses per element, so one does not cancel another', () => {
        const other = document.createElement('div');
        document.body.append(other);

        pulseElement(el);
        vi.advanceTimersByTime(400);
        pulseElement(other);

        vi.advanceTimersByTime(2 * CYCLE_MS + SLACK_MS - 400);
        expect(el.classList.contains(PULSE_CLASS)).toBe(false);
        expect(other.classList.contains(PULSE_CLASS)).toBe(true);
    });
});

describe('pulse requests', () => {
    // For pulsing a target the requester cannot reach — a hand-off names it
    // before the panel showing it has rendered.

    it('does not pulse anything that was never asked for', () => {
        // The regression this exists for: the credentials tab used to pulse on
        // every open where a node still needed an account, which fires on the
        // visits where the user already knows why they are there.
        expect(claimPulse(credentialsPulseKey('n1'))).toBe(false);
    });

    it('is claimable by the named target, once', () => {
        requestPulse(credentialsPulseKey('n1'));
        expect(claimPulse(credentialsPulseKey('n1'))).toBe(true);
        // The second claim is the other ordering arriving late; consuming the
        // request is what stops one hand-off pulsing twice.
        expect(claimPulse(credentialsPulseKey('n1'))).toBe(false);
    });

    it('is not claimable by a different target', () => {
        requestPulse(credentialsPulseKey('n1'));
        expect(claimPulse(credentialsPulseKey('n2'))).toBe(false);
    });

    it('expires, so an abandoned hand-off cannot fire later', () => {
        requestPulse(credentialsPulseKey('n1'));
        vi.advanceTimersByTime(5001);
        expect(claimPulse(credentialsPulseKey('n1'))).toBe(false);
    });

    it('notifies listeners so an already-mounted target can claim it', () => {
        const seen: string[] = [];
        const stop = onPulseRequested(key => seen.push(key));
        requestPulse(credentialsPulseKey('n1'));
        expect(seen).toEqual([credentialsPulseKey('n1')]);

        stop();
        requestPulse(credentialsPulseKey('n2'));
        expect(seen).toEqual([credentialsPulseKey('n1')]);
    });

    it('leaves the request alone until something claims it', () => {
        // Mount order is not guaranteed: the target may appear a beat after the
        // request, which is the whole reason this is not just an event.
        requestPulse(credentialsPulseKey('n1'));
        vi.advanceTimersByTime(400);
        expect(claimPulse(credentialsPulseKey('n1'))).toBe(true);
    });
});

describe('pulseElement — element isolation', () => {
    it('tracks pulses per element, so one does not cancel another', () => {
        const other = document.createElement('div');
        document.body.append(other);

        pulseElement(el);
        vi.advanceTimersByTime(400);
        pulseElement(other);

        vi.advanceTimersByTime(2 * CYCLE_MS + SLACK_MS - 400);
        expect(el.classList.contains(PULSE_CLASS)).toBe(false);
        expect(other.classList.contains(PULSE_CLASS)).toBe(true);
    });
});
