// @vitest-environment jsdom
// A build card says where its build stands in its header: at work, a working mark beside "Building" and the part that
// just landed under the name; built, a check, drawn in when the card saw it finish; waiting on you, or stopped.
import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { AgentPreviewCard, BuildStatus, type BuildPart, type BuildState } from '~/components/coordinator/inline/setup';
import { registerCoordinatorCanvas } from '~/components/coordinator/inline/canvas';

registerCoordinatorCanvas(() => <div data-testid="canvas" />);
afterEach(cleanup);

const BLOB = { nodes: [{ id: 'agent', type: 'agent', position: { x: 0, y: 0 }, config: {} }], edges: [] };
const CRON: BuildPart = { type: 'trigger-cron', label: 'Every weekday' };
const AGENT: BuildPart = { type: 'agent', label: 'Claude Code' };
const SLACK: BuildPart = { type: 'automation-slack', label: 'Slack' };

const card = (state: BuildState, parts: BuildPart[] = [CRON, AGENT]) => <AgentPreviewCard blob={BLOB} name="Morning brief" state={state} parts={parts} />;
// While one state swaps for the next, the one leaving still draws first.
const status = () => screen.getAllByTestId('build-status').at(-1)!;

describe('a build card’s status', () => {
    it.each([
        ['building', 'Building'],
        ['done', 'Built'],
        ['waiting', 'Needs you'],
        ['failed', 'Stopped'],
    ] as const)('%s reads “%s”', (state, word) => {
        render(card(state));
        expect(status().dataset.state).toBe(state);
        expect(status().textContent).toBe(word);
    });

    it('marks a build at work with the turn’s working orb, never a spinner', () => {
        render(card('building'));
        expect(status().querySelector('canvas')).toBeTruthy();
        expect(status().querySelector('.animate-spin')).toBeNull();
    });

    it('has the lab’s other looks: long work’s live dot, or light across the word', () => {
        const { rerender } = render(<BuildStatus state="building" look="dot" />);
        expect(status().querySelector('.animate-ping')).toBeTruthy();
        rerender(<BuildStatus state="building" look="shine" />);
        expect(status().querySelector('.tl-shine')?.textContent).toBe('Building');
        expect(status().querySelector('canvas, .animate-ping')).toBeNull();
    });

    it('draws its check in when it saw the build finish, and shows it still when read back done', () => {
        const { rerender } = render(card('building'));
        rerender(card('done'));
        expect(status().querySelector('.sc-draw')).toBeTruthy();
        cleanup();
        render(card('done'));
        expect(status().querySelector('.sc-draw')).toBeNull();
        expect(status().querySelector('svg')).toBeTruthy();
    });

    it('names the part that just landed under its name, and how many parts it came to', () => {
        const { rerender } = render(card('building', [CRON, AGENT]));
        expect(screen.getByText('Adding Claude Code…')).toBeTruthy();
        // A part landing before the others in the flow's order is still the one named.
        rerender(card('building', [SLACK, CRON, AGENT]));
        expect(screen.getByText('Adding Slack…')).toBeTruthy();
        rerender(card('done', [SLACK, CRON, AGENT]));
        expect(screen.getByText('3 parts')).toBeTruthy();
    });

    it('has no status while the build can’t be followed from here', () => {
        render(<AgentPreviewCard blob={BLOB} name="Morning brief" meta="Building now." state="started" parts={[AGENT]} />);
        expect(screen.queryByTestId('build-status')).toBeNull();
    });
});
