// Pins orbStateForStatus against the status strings the agentic builder
// actually emits (backend/coder/workflow/agentic/builder.py: _status_for_ops
// plus the per-op lines). The mapping is what makes the orb mean something —
// if a backend status verb drifts, the orb silently degrades to the generic
// `working` animation, and this test is what catches that.
import { describe, it, expect } from 'vitest';
import { orbStateForStatus } from '~/components/shared/ThinkingOrb';

describe('orbStateForStatus', () => {
    it('maps every status _status_for_ops can return', () => {
        // Verbatim from backend _status_for_ops.
        expect(orbStateForStatus('Searching workflows')).toBe('searching');
        expect(orbStateForStatus('Searching credentials')).toBe('searching');
        expect(orbStateForStatus('Looking up node info')).toBe('searching');
        expect(orbStateForStatus('Reading config')).toBe('searching');
        expect(orbStateForStatus('Reading documentation')).toBe('searching');
        expect(orbStateForStatus('Reading node output')).toBe('searching');
        expect(orbStateForStatus('Connecting nodes')).toBe('connecting');
        expect(orbStateForStatus('Modifying workflow')).toBe('weaving');
        expect(orbStateForStatus('Creating workflow')).toBe('weaving');
        expect(orbStateForStatus('Updating config')).toBe('weaving');
        // No dedicated orb — these are generic busy work.
        expect(orbStateForStatus('Opening workflow')).toBe('working');
        expect(orbStateForStatus('Managing folders')).toBe('working');
        expect(orbStateForStatus('Running node')).toBe('working');
    });

    it('maps the interpolated per-op statuses', () => {
        expect(orbStateForStatus('Looking up operations for slack')).toBe(
            'searching'
        );
        expect(orbStateForStatus('Reading schema for Slack: send')).toBe(
            'searching'
        );
        expect(orbStateForStatus('Reading config for node_1')).toBe(
            'searching'
        );
        expect(orbStateForStatus("Searching workflows for 'invoices'")).toBe(
            'searching'
        );
        expect(orbStateForStatus('Creating folder Ops')).toBe('weaving');
    });

    it('leaves the builder thinking pause on the house style', () => {
        expect(orbStateForStatus('Thinking')).toBe('working');
        // MobileBuilderStatusPill's own default carries an ellipsis.
        expect(orbStateForStatus('Thinking…')).toBe('working');
    });

    it('maps frontend edit-step lines', () => {
        expect(orbStateForStatus('Adding Slack node')).toBe('weaving');
        expect(orbStateForStatus('Configuring Gmail')).toBe('weaving');
        expect(orbStateForStatus('Removing node_2')).toBe('weaving');
    });

    it('defaults to working for absent or unrecognised status', () => {
        expect(orbStateForStatus(undefined)).toBe('working');
        expect(orbStateForStatus(null)).toBe('working');
        expect(orbStateForStatus('')).toBe('working');
        expect(orbStateForStatus('Working')).toBe('working');
        // The op-limit retry line — free text, no leading verb we map.
        expect(
            orbStateForStatus(
                'Hit 40-op-per-turn limit — discarding response and retrying with a smaller batch'
            )
        ).toBe('working');
    });

    it('ignores surrounding whitespace and case', () => {
        expect(orbStateForStatus('  searching workflows  ')).toBe('searching');
        expect(orbStateForStatus('READING config')).toBe('searching');
    });
});
